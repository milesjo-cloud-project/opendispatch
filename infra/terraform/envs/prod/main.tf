terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Local state for now. When you move to GCP, create the bucket, uncomment,
  # and run: terraform init -migrate-state
  # backend "gcs" {
  #   bucket = "opendispatch-tfstate"
  #   prefix = "prod"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type    = string
  default = "opendispatch-prod"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "github_repo" {
  type        = string
  description = "owner/repo, e.g. miles/opendispatch"
}

module "app" {
  source      = "../../modules/app"
  project_id  = var.project_id
  region      = var.region
  env         = "prod"
  github_repo = var.github_repo
}

output "workload_identity_provider" { value = module.app.workload_identity_provider }
output "deployer_service_account" { value = module.app.deployer_service_account }
output "image_repo" { value = module.app.image_repo }
output "api_url" { value = module.app.api_url }
