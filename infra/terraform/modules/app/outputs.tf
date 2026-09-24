output "workload_identity_provider" {
  description = "Put this in the GitHub repo variable WIF_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "Put this in the GitHub repo variable DEPLOYER_SA"
  value       = google_service_account.deployer.email
}

output "image_repo" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}
