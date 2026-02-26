terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ── Enable APIs ──────────────────────────────────────────────────────────────
resource "google_project_service" "run" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}
resource "google_project_service" "firestore" {
  service            = "firestore.googleapis.com"
  disable_on_destroy = false
}
resource "google_project_service" "artifact_registry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}
resource "google_project_service" "storage" {
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

# ── Artifact Registry — Docker repo for container images ────────────────────
resource "google_artifact_registry_repository" "repo" {
  repository_id = "visual-qa-sniper"
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.artifact_registry]
}

# ── Firestore database ───────────────────────────────────────────────────────
resource "google_firestore_database" "db" {
  name        = "(default)"
  location_id = "nam5"           # US multi-region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.firestore]
}

# ── Cloud Run service ────────────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "api" {
  name     = "visual-qa-sniper"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    # Headless Chromium needs more RAM
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/visual-qa-sniper/backend:latest"

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }

      env {
        name  = "GOOGLE_API_KEY"
        value = var.gemini_api_key
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "FIRESTORE_COLLECTION"
        value = "qa_sessions"
      }
    }

    # Allow one request to spin up a new instance (WebSocket)
    max_instance_request_concurrency = 10
  }

  depends_on = [google_project_service.run]
}

# ── Make backend publicly accessible ────────────────────────────────────────
resource "google_cloud_run_service_iam_member" "public" {
  location = google_cloud_run_v2_service.api.location
  project  = google_cloud_run_v2_service.api.project
  service  = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
