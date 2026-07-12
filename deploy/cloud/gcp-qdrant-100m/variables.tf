variable "project_id" {
  description = "Google Cloud project used for the isolated 100M Qdrant evidence lab."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project ID."
  }
}

variable "deployment_id" {
  type    = string
  default = "wavemind-100m-gcp"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,62}$", var.deployment_id))
    error_message = "deployment_id must be a lowercase DNS-style identifier."
  }
}

variable "shards" {
  description = "Eight or more shard hosts in unique zones across at least three regions."
  type = map(object({
    region = string
    zone   = string
  }))
  default = {
    shard-0 = { region = "europe-west1", zone = "europe-west1-b" }
    shard-1 = { region = "europe-west1", zone = "europe-west1-c" }
    shard-2 = { region = "us-east1", zone = "us-east1-b" }
    shard-3 = { region = "us-east1", zone = "us-east1-c" }
    shard-4 = { region = "asia-south1", zone = "asia-south1-a" }
    shard-5 = { region = "asia-south1", zone = "asia-south1-b" }
    shard-6 = { region = "europe-central2", zone = "europe-central2-a" }
    shard-7 = { region = "europe-central2", zone = "europe-central2-b" }
  }

  validation {
    condition = (
      length(var.shards) >= 8 &&
      length(distinct([for config in values(var.shards) : config.region])) >= 3 &&
      length(distinct([for config in values(var.shards) : config.zone])) == length(var.shards) &&
      alltrue([for id in keys(var.shards) : can(regex("^[a-z][a-z0-9-]{1,62}$", id))])
    )
    error_message = "shards must contain at least eight unique zones across at least three regions."
  }
}

variable "target_vectors" {
  type    = number
  default = 100000000

  validation {
    condition     = var.target_vectors >= 100000000
    error_message = "target_vectors must be at least 100000000."
  }
}

variable "vector_dim" {
  type    = number
  default = 128

  validation {
    condition     = var.vector_dim >= 1
    error_message = "vector_dim must be positive."
  }
}

variable "qdrant_image" {
  description = "Exact Qdrant semver or sha256 digest used by the remote deployer."
  type        = string
  default     = "qdrant/qdrant:v1.18.2"

  validation {
    condition = can(regex(
      "^qdrant/qdrant(:v[0-9]+\\.[0-9]+\\.[0-9]+|@sha256:[0-9a-f]{64})$",
      var.qdrant_image,
    ))
    error_message = "qdrant_image must pin an exact Qdrant semver or sha256 digest."
  }
}

variable "network_name" {
  type    = string
  default = "default"
}

variable "machine_type" {
  description = "At least 16 GB RAM is required by strict attestation."
  type        = string
  default     = "e2-standard-4"
}

variable "boot_disk_size_gb" {
  description = "Per-shard disk. Strict attestation requires at least 35 GB free."
  type        = number
  default     = 100

  validation {
    condition     = var.boot_disk_size_gb >= 60
    error_message = "boot_disk_size_gb must be at least 60 GB."
  }
}

variable "boot_image" {
  type    = string
  default = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
}

variable "ssh_user" {
  type    = string
  default = "wavemind"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.ssh_user))
    error_message = "ssh_user must be a valid Linux account name."
  }
}

variable "ssh_public_key" {
  description = "Public SSH key only. Keep the matching private key outside Terraform state."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^(ssh-ed25519|ecdsa-sha2-nistp256|sk-ssh-ed25519@openssh.com) [A-Za-z0-9+/=]+(?: .*)?$", trimspace(var.ssh_public_key)))
    error_message = "ssh_public_key must be a supported public OpenSSH key."
  }
}

variable "ssh_source_ranges" {
  description = "CIDRs allowed to reach SSH. Qdrant itself is never exposed."
  type        = list(string)

  validation {
    condition = (
      length(var.ssh_source_ranges) > 0 &&
      !contains(var.ssh_source_ranges, "0.0.0.0/0") &&
      alltrue([for cidr in var.ssh_source_ranges : can(cidrhost(cidr, 0))])
    )
    error_message = "ssh_source_ranges must contain valid restricted CIDRs and may not include 0.0.0.0/0."
  }
}

variable "deletion_protection" {
  type    = bool
  default = true
}
