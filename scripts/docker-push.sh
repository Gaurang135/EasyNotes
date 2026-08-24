#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EasyNotes — log in to Docker Hub, build the image for linux/amd64, and push it.
# Image name:  docker.io/$DOCKER_USER/easynotes  (tagged :latest and :<git-sha>).
# Builds linux/amd64 explicitly so the image runs on Render / most cloud hosts even
# when you build on an Apple-Silicon (arm64) Mac. On arm64 this cross-builds via
# emulation (slower, but the onnxruntime/sqlite-vec wheels all have amd64 builds).
# Override the target arch with PLATFORM=linux/arm64 (or a comma list for multi-arch).
# DOCKER_USER is set in the Makefile (or the environment); this script refuses to run
# until it's a real username.
#   make docker-push                    # uses DOCKER_USER from the Makefile
#   DOCKER_USER=me TAG=v1 bash scripts/docker-push.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

DOCKER_USER="${DOCKER_USER:-}"
TAG="${TAG:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"   # Render requires linux/amd64

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

echo "==> build ${IMAGE} for ${PLATFORM} and push (:${TAG}${SHA:+ , :${SHA}})"
if docker buildx version >/dev/null 2>&1; then
  # buildx: cross-build the target platform and push the result directly.
  tags=(-t "${IMAGE}:${TAG}")
  [ -n "$SHA" ] && tags+=(-t "${IMAGE}:${SHA}")
  docker buildx build --platform "${PLATFORM}" "${tags[@]}" --push .
else
  # fallback for daemons without buildx: single-arch build (emulated) then push.
  case "$PLATFORM" in *,*)
    echo "ERROR: multi-arch ($PLATFORM) needs buildx, which isn't available." >&2; exit 1;; esac
  docker build --platform "${PLATFORM}" -t "${IMAGE}:${TAG}" .
  [ -n "$SHA" ] && docker tag "${IMAGE}:${TAG}" "${IMAGE}:${SHA}"
  docker push "${IMAGE}:${TAG}"
  [ -n "$SHA" ] && docker push "${IMAGE}:${SHA}"
fi

echo "Done — pushed ${PLATFORM} image ${IMAGE}:${TAG}${SHA:+ and :${SHA}}"