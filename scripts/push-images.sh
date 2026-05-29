#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REGISTRY="${ACR_REGISTRY:-rahulaiservices.azurecr.io}"
ACR_NAME="${ACR_NAME:-rahulaiservices}"
TAG="${IMAGE_TAG:-latest}"

IMAGES=(
  email-service
  whatsapp-service
  app
  llm-worker
  ocr-worker
  so-worker
)

echo "Logging in to Azure Container Registry (${ACR_NAME})..."
az acr login --name "${ACR_NAME}"

echo "Tagging and pushing images to ${REGISTRY} (tag: ${TAG})..."

for image in "${IMAGES[@]}"; do
  remote="${REGISTRY}/${image}:${TAG}"
  echo "  ${image}:${TAG} -> ${remote}"
  docker tag "${image}:${TAG}" "${remote}"
  docker push "${remote}"
done

echo "Pushed images:"
for image in "${IMAGES[@]}"; do
  echo "  - ${REGISTRY}/${image}:${TAG}"
done
