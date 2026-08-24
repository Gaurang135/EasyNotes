#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EasyNotes — log in to Docker Hub, build the image, and push it.
# Image name:  docker.io/$DOCKER_USER/easynotes  (tagged :latest and :<git-sha>).
# DOCKER_USER is set in the Makefile (or the environment); this script refuses
# to run until it's a real username.
#   make docker-push                    # uses DOCKER_USER from the Makefile
#   DOCKER_USER=me TAG=v1 bash scripts/docker-push.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

DOCKER_USER="${DOCKER_USER:-}"
TAG="${TAG:-latest}"

if [ -z "$DOCKER_USER" ] || [ "$DOCKER_USER" = "CHANGEME" ]; then
  echo "ERROR: DOCKER_USER is not set. Edit DOCKER_USER at the top of the Makefile" >&2
  echo "       (your Docker Hub username), or run: DOCKER_USER=<you> make docker-push" >&2
  exit 1
fi
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found." >&2; exit 1; }

IMAGE="docker.io/${DOCKER_USER}/easynotes"
SHA="$(git rev-parse --short HEAD 2>/dev/null || true)"

echo "==> docker login (Docker Hub)"
docker login

echo "==> build ${IMAGE}:${TAG}"
docker build -t "${IMAGE}:${TAG}" .
[ -n "$SHA" ] && docker tag "${IMAGE}:${TAG}" "${IMAGE}:${SHA}"

echo "==> push ${IMAGE}:${TAG}"
docker push "${IMAGE}:${TAG}"
if [ -n "$SHA" ]; then
  echo "==> push ${IMAGE}:${SHA}"
  docker push "${IMAGE}:${SHA}"
fi

echo "Done — pushed ${IMAGE}:${TAG}${SHA:+ and :${SHA}}"
