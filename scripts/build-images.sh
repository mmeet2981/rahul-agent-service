#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

TAG="${IMAGE_TAG:-latest}"

IMAGES=(
  email-service
  whatsapp-service
  app
  llm-worker
  ocr-worker
  so-worker
)

echo "Building production images (tag: ${TAG})..."

docker build -t "email-service:${TAG}" ./email-service
docker build -t "whatsapp-service:${TAG}" ./whatsapp-service

# App and workers share the same Dockerfile and build context.
docker build -t "app:${TAG}" -f Dockerfile .
docker tag "app:${TAG}" "llm-worker:${TAG}"
docker tag "app:${TAG}" "ocr-worker:${TAG}"
docker tag "app:${TAG}" "so-worker:${TAG}"

echo "Built images:"
for image in "${IMAGES[@]}"; do
  echo "  - ${image}:${TAG}"
done
