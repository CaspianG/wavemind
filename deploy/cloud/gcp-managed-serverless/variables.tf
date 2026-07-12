variable "project_id" {
  description = "Google Cloud project used for the dedicated WaveMind evidence service."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Dedicated Cloud Run service used only for managed-serverless evidence."
  type        = string
  default     = "wavemind-managed-evidence"
}

variable "image" {
  description = "Existing immutable Artifact Registry image digest. Tags are rejected."
  type        = string

  validation {
    condition = can(regex(
      "^[a-z0-9-]+-docker\\.pkg\\.dev/[a-z][a-z0-9-]+/[a-z0-9._-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$",
      var.image,
    ))
    error_message = "image must be an immutable Artifact Registry sha256 digest."
  }
}

variable "github_repository" {
  description = "Only this GitHub repository may exchange OIDC tokens."
  type        = string
  default     = "CaspianG/wavemind"
}

variable "github_ref" {
  description = "Only this Git ref may exchange OIDC tokens."
  type        = string
  default     = "refs/heads/main"
}

variable "workload_identity_pool_id" {
  type    = string
  default = "wavemind-github"
}

variable "workload_identity_provider_id" {
  type    = string
  default = "wavemind-main"
}

variable "runtime_service_account_id" {
  type    = string
  default = "wavemind-managed-runtime"
}

variable "evidence_service_account_id" {
  type    = string
  default = "wavemind-evidence-runner"
}

variable "artifact_registry_repository_id" {
  type    = string
  default = "wavemind"
}

variable "secret_env" {
  description = "Existing Secret Manager secret IDs mapped to required WaveMind environment variables."
  type        = map(string)

  validation {
    condition = toset(keys(var.secret_env)) == toset([
      "WAVEMIND_POSTGRES_DSN",
      "WAVEMIND_QDRANT_URL",
      "WAVEMIND_REDIS_URL",
      "WAVEMIND_API_KEYS",
    ])
    error_message = "secret_env must define exactly the four required WaveMind secret variables."
  }
}

variable "max_instances" {
  description = "Cloud Run max instances. Strict evidence requires at least two."
  type        = number
  default     = 16

  validation {
    condition     = var.max_instances >= 2 && var.max_instances <= 1000
    error_message = "max_instances must be between 2 and 1000."
  }
}

variable "container_concurrency" {
  type    = number
  default = 80
}

variable "cpu" {
  type    = string
  default = "2"
}

variable "memory" {
  type    = string
  default = "2Gi"
}

variable "vpc_connector" {
  description = "Optional fully qualified Serverless VPC Access connector."
  type        = string
  default     = null
  nullable    = true
}

variable "deletion_protection" {
  description = "Protect the dedicated evidence service from accidental Terraform destroy."
  type        = bool
  default     = true
}
