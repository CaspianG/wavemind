output "regional_addresses" {
  description = "Static public addresses of the three independent evidence hosts."
  value = {
    for id, address in google_compute_address.region : id => address.address
  }
}

output "remote_lab_inventory" {
  description = "Structured inventory consumed by deploy/remote/remote_lab.py."
  value = {
    schema        = "wavemind.remote_production_lab.v1"
    deployment_id = var.deployment_id
    environment   = "staging"
    source        = "gcp-compute-terraform"
    image         = var.wavemind_image
    regions = [
      for id in sort(keys(var.regions)) : {
        id         = id
        ssh_host   = "${var.ssh_user}@${google_compute_address.region[id].address}"
        public_url = "http://${google_compute_address.region[id].address}:8000"
        region     = var.regions[id].region
        zone       = var.regions[id].zone
        provider   = "gcp"
        http_port  = 8000
      }
    ]
  }
}

output "remote_lab_inventory_json" {
  description = "Store this JSON as WAVEMIND_REMOTE_LAB_INVENTORY_JSON after reviewing it."
  value = jsonencode({
    schema        = "wavemind.remote_production_lab.v1"
    deployment_id = var.deployment_id
    environment   = "staging"
    source        = "gcp-compute-terraform"
    image         = var.wavemind_image
    regions = [
      for id in sort(keys(var.regions)) : {
        id         = id
        ssh_host   = "${var.ssh_user}@${google_compute_address.region[id].address}"
        public_url = "http://${google_compute_address.region[id].address}:8000"
        region     = var.regions[id].region
        zone       = var.regions[id].zone
        provider   = "gcp"
        http_port  = 8000
      }
    ]
  })
}

output "known_hosts_command" {
  description = "Run after first boot, verify fingerprints out of band, then store output as WAVEMIND_REMOTE_SSH_KNOWN_HOSTS."
  value       = "ssh-keyscan -H ${join(" ", [for id in sort(keys(var.regions)) : google_compute_address.region[id].address])}"
}
