#!/usr/bin/env bash
# deploy.sh — One-command build and deploy to Google Cloud Run
# Usage: bash deploy.sh YOUR_PROJECT_ID YOUR_REGION

set -e

PROJECT_ID="${1:-your-gcp-project-id}"
REGION="${2:-us-central1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/visual-qa-sniper/backend:latest"

echo "==> Configuring Docker for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "==> Building Docker image..."
docker build -t "$IMAGE" .

echo "==> Pushing image to Artifact Registry..."
docker push "$IMAGE"

echo "==> Applying Terraform..."
cd terraform
terraform init -upgrade
terraform apply -auto-approve \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="gemini_api_key=${GOOGLE_API_KEY}"

echo ""
echo "✅ Deployment complete!"
terraform output backend_url
