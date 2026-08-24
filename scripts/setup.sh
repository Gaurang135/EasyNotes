#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# EasyNotes — project setup (portable core, no Homebrew/Docker).
# Creates the virtualenv, installs dependencies, and bootstraps a .env.
# Idempotent: safe to run repeatedly. Invoked by `make setup`.
#   Override the interpreter:  PY=python3 bash scripts/setup.sh
# For a from-scratch macOS box (installs brew/python/docker) use scripts/setup-mac.sh.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

PY="${PY:-python3.12}"
VENV=".venv"
info() { printf "\033[36m==> %s\033[0m\n" "$1"; }

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: '$PY' not found. Install Python 3.12 (macOS: brew install python@3.12)," >&2
  echo "       or re-run as: PY=python3 bash scripts/setup.sh" >&2
  exit 1
fi

info "Creating virtualenv ($VENV) with $($PY --version)"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"

info "Upgrading pip"
"$VENV/bin/pip" install --quiet --upgrade pip

info "Installing dependencies (requirements-dev.txt → pulls in requirements.txt)"
"$VENV/bin/pip" install --quiet -r requirements-dev.txt

if [ ! -f .env ] && [ -f .env.example ]; then
  info "Creating .env from .env.example — fill in ANSWER_API_KEY to enable Ask (optional)"
  cp .env.example .env
fi

info "Setup complete. Next: 'make run' (local) or 'make docker-run' (container)."
