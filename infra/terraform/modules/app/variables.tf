variable "project_id" {
  type        = string
  description = "GCP project id, e.g. opendispatch-dev"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "env" {
  type        = string
  description = "dev or prod"
}

variable "github_repo" {
  type        = string
  description = "owner/repo allowed to deploy through Workload Identity Federation, e.g. miles/opendispatch"
}

variable "secret_names" {
  type        = list(string)
  description = "Secret Manager containers to create. Values are added by hand, never in Terraform."
  default     = ["database-url"]
}

variable "allow_public" {
  type        = bool
  description = "Let anyone call the Cloud Run service (fine for the hello-world phase)"
  default     = true
}
