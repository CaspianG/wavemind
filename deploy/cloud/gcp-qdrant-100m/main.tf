locals {
  instance_tag = "${var.deployment_id}-shard"
}

resource "google_project_service" "compute" {
  project            = var.project_id
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_address" "shard" {
  for_each = var.shards

  project      = var.project_id
  name         = "${var.deployment_id}-${each.key}"
  region       = each.value.region
  address_type = "EXTERNAL"

  depends_on = [google_project_service.compute]
}

resource "google_compute_firewall" "ssh" {
  project       = var.project_id
  name          = "${var.deployment_id}-ssh"
  network       = var.network_name
  direction     = "INGRESS"
  source_ranges = var.ssh_source_ranges
  target_tags   = [local.instance_tag]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  depends_on = [google_project_service.compute]
}

resource "google_compute_instance" "shard" {
  for_each = var.shards

  project                   = var.project_id
  name                      = "${var.deployment_id}-${each.key}"
  zone                      = each.value.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  deletion_protection       = var.deletion_protection
  tags                      = [local.instance_tag]

  labels = {
    component   = "qdrant"
    environment = "evidence"
    shard_id    = each.key
  }

  boot_disk {
    auto_delete = true

    initialize_params {
      image = var.boot_image
      size  = var.boot_disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = var.network_name

    access_config {
      nat_ip = google_compute_address.shard[each.key].address
    }
  }

  metadata = {
    block-project-ssh-keys = "true"
    ssh-keys               = "${var.ssh_user}:${trimspace(var.ssh_public_key)}"
  }

  metadata_startup_script = templatefile("${path.module}/startup.sh.tftpl", {
    ssh_user = var.ssh_user
  })

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  depends_on = [google_compute_firewall.ssh]
}
