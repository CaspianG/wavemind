output "cloud_run_service_url" {
  value       = google_cloud_run_v2_service.wavemind.uri
  description = "IAM-protected Cloud Run service URL."
}

output "cloud_run_service_name" {
  value = google_cloud_run_v2_service.wavemind.name
}

output "artifact_registry_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.wavemind.repository_id}"
}

output "github_workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Store as the WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER GitHub secret."
}

output "github_evidence_service_account" {
  value       = google_service_account.evidence.email
  description = "Store as the WAVEMIND_GCP_SERVICE_ACCOUNT GitHub secret."
}

output "github_repository_variables" {
  value = {
    WAVEMIND_CLOUD_RUN_PROJECT_ID = var.project_id
    WAVEMIND_CLOUD_RUN_REGION     = var.region
    WAVEMIND_CLOUD_RUN_SERVICE    = google_cloud_run_v2_service.wavemind.name
  }
}
