variable "project_id" {
  description = "Google Cloud project used for the isolated active-active evidence lab."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project ID."
  }
}

variable "deployment_id" {
  description = "Stable DNS-style identifier written into the strict evidence inventory."
  type        = string
  default     = "wavemind-gcp-regions"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,62}$", var.deployment_id))
    error_message = "deployment_id must be a lowercase DNS-style identifier."
  }
}

variable "regions" {
  description = "Independent GCP regions and zones. At least three are required."
  type = map(object({
    region = string
    zone   = string
  }))
  default = {
    eu-west = {
      region = "europe-west1"
      zone   = "europe-west1-b"
    }
    us-east = {
      region = "us-east1"
      zone   = "us-east1-b"
    }
    ap-south = {
      region = "asia-south1"
      zone   = "asia-south1-a"
    }
  }

  validation {
    condition = (
      length(var.regions) >= 3 &&
      length(distinct([for config in values(var.regions) : config.region])) == length(var.regions) &&
      length(distinct([for config in values(var.regions) : config.zone])) == length(var.regions) &&
      alltrue([for id in keys(var.regions) : can(regex("^[a-z][a-z0-9-]{1,62}$", id))])
    )
    error_message = "regions must contain at least three unique regions/zones with DNS-style IDs."
  }
}

variable "network_name" {
  description = "Existing VPC network shared by the regional evidence VMs."
  type        = string
  default     = "default"
}

variable "machine_type" {
  description = "Machine type for each regional WaveMind stack."
  type        = string
  default     = "e2-standard-2"
}

variable "boot_disk_size_gb" {
  type    = number
  default = 50

  validation {
    condition     = var.boot_disk_size_gb >= 30
    error_message = "boot_disk_size_gb must be at least 30 GB."
  }
}

variable "boot_image" {
  description = "Pinned image family used for the remote Linux hosts."
  type        = string
  default     = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64"
}

variable "wavemind_image" {
  description = "Immutable WaveMind GHCR release or commit image used by the remote deployer."
  type        = string

  validation {
    condition = can(regex(
      "^ghcr\\.io/[a-z0-9._-]+/[a-z0-9._-]+:(v?[0-9]+\\.[0-9]+\\.[0-9]+|sha-[0-9a-f]{7,64})$",
      var.wavemind_image,
    ))
    error_message = "wavemind_image must be an immutable GHCR release or sha tag."
  }
}

variable "ssh_user" {
  description = "Linux user created for the attested SSH deployer."
  type        = string
  default     = "wavemind"

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
  description = "CIDRs allowed to reach SSH. Never use 0.0.0.0/0."
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

variable "api_source_ranges" {
  description = "CIDRs allowed to reach the API evidence port. Explicit public access is permitted only for ephemeral API-key-protected labs."
  type        = list(string)

  validation {
    condition = (
      length(var.api_source_ranges) > 0 &&
      alltrue([for cidr in var.api_source_ranges : can(cidrhost(cidr, 0))])
    )
    error_message = "api_source_ranges must contain at least one valid CIDR."
  }
}

variable "deletion_protection" {
  description = "Protect evidence VMs from accidental Terraform destroy."
  type        = bool
  default     = true
}
