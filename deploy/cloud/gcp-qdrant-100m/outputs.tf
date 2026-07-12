locals {
  inventory = {
    schema         = "wavemind.remote_qdrant_scale_lab.v1"
    deployment_id  = var.deployment_id
    environment    = "staging"
    source         = "gcp-compute-terraform"
    image          = var.qdrant_image
    target_vectors = var.target_vectors
    vector_dim     = var.vector_dim
    shards = [
      for id in sort(keys(var.shards)) : {
        id          = id
        ssh_host    = "${var.ssh_user}@${google_compute_address.shard[id].address}"
        region      = var.shards[id].region
        zone        = var.shards[id].zone
        provider    = "gcp"
        qdrant_port = 6333
      }
    ]
  }
}

output "shard_addresses" {
  value = {
    for id, address in google_compute_address.shard : id => address.address
  }
}

output "remote_scale_inventory" {
  description = "Structured inventory consumed by deploy/remote-scale/remote_scale_lab.py."
  value       = local.inventory
}

output "remote_scale_inventory_json" {
  description = "Store as WAVEMIND_REMOTE_SCALE_INVENTORY_JSON after review."
  value       = jsonencode(local.inventory)
}

output "known_hosts_command" {
  description = "Verify fingerprints out of band before storing the output as a GitHub secret."
  value = "ssh-keyscan -H ${join(" ", [
    for id in sort(keys(var.shards)) : google_compute_address.shard[id].address
  ])}"
}

output "runner" {
  description = "Dedicated controller. Registration is deliberately performed after apply with a short-lived token."
  value = var.create_runner ? {
    address      = google_compute_address.runner[0].address
    ssh_host     = "${var.ssh_user}@${google_compute_address.runner[0].address}"
    custom_label = "self-hosted-large"
    repository   = var.runner_repository
  } : null
}

output "runner_known_hosts_command" {
  value = var.create_runner ? "ssh-keyscan -H ${google_compute_address.runner[0].address}" : null
}
