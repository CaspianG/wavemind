locals {
  required_apis = toset([
    "artifactregistry.googleapis.com",
    "iamcredentials.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com",
  ])
  evidence_project_roles = toset([
    "roles/monitoring.viewer",
    "roles/run.viewer",
    "roles/serviceusage.serviceUsageConsumer",
  ])
  github_principal = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_project_service" "required" {
  for_each = local.required_apis

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "wavemind" {
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_registry_repository_id
  description   = "Immutable WaveMind images for managed-serverless evidence"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = var.runtime_service_account_id
  display_name = "WaveMind managed serverless runtime"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "evidence" {
  project      = var.project_id
  account_id   = var.evidence_service_account_id
  display_name = "WaveMind GitHub evidence collector"

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = var.workload_identity_pool_id
  display_name              = "WaveMind GitHub Actions"
  description               = "Short-lived OIDC trust for the WaveMind main branch"

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.workload_identity_provider_id
  display_name                       = "WaveMind main branch"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.ref == '${var.github_ref}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_workload_identity" {
  service_account_id = google_service_account.evidence.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_principal
}

resource "google_project_iam_member" "evidence" {
  for_each = local.evidence_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.evidence.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each = var.secret_env

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "wavemind" {
  project             = var.project_id
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.deletion_protection

  scaling {
    min_instance_count = 0
    max_instance_count = var.max_instances
  }

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "300s"
    max_instance_request_concurrency = var.container_concurrency

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    dynamic "vpc_access" {
      for_each = var.vpc_connector == null ? [] : [var.vpc_connector]
      content {
        connector = vpc_access.value
        egress    = "PRIVATE_RANGES_ONLY"
      }
    }

    containers {
      image = var.image

      ports {
        name           = "http1"
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      startup_probe {
        initial_delay_seconds = 0
        timeout_seconds       = 5
        period_seconds        = 5
        failure_threshold     = 24

        tcp_socket {
          port = 8000
        }
      }

      liveness_probe {
        initial_delay_seconds = 10
        timeout_seconds       = 5
        period_seconds        = 10
        failure_threshold     = 6

        http_get {
          path = "/health"
          port = 8000
        }
      }

      env {
        name  = "WAVEMIND_STORE"
        value = "postgres"
      }
      env {
        name  = "WAVEMIND_INDEX"
        value = "qdrant"
      }
      env {
        name  = "WAVEMIND_ENCODER"
        value = "hash"
      }
      env {
        name  = "WAVEMIND_AUDIT_QUERIES"
        value = "1"
      }
      env {
        name  = "WAVEMIND_SHARED_STORE_REFRESH_SECONDS"
        value = "0.5"
      }

      dynamic "env" {
        for_each = var.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_artifact_registry_repository.wavemind,
    google_secret_manager_secret_iam_member.runtime,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "evidence_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.wavemind.location
  name     = google_cloud_run_v2_service.wavemind.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.evidence.email}"
}
