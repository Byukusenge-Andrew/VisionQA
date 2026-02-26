output "backend_url" {
  description = "Public URL of the deployed Visual QA Sniper backend"
  value       = google_cloud_run_v2_service.api.uri
}
