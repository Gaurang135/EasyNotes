#!/usr/bin/env bash
# EasyNotes macOS bootstrap: installs Homebrew, Python 3.12, Docker, and project deps.
set -euo pipefail

info() { printf "\033[36m==> %s\033[0m\n" "$1"; }

if ! command -v brew >/dev/null 2>&1; then
  info "Installing Homebrew"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$($(/usr/bin/which brew || echo /opt/homebrew/bin/brew) shellenv)"
else
  info "Homebrew present"
fi

info "Installing Python 3.12"
brew install python@3.12 || brew upgrade python@3.12 || true

if ! command -v docker >/dev/null 2>&1; then
  info "Installing Docker Desktop (cask)"
  brew install --cask docker
  echo "Open Docker Desktop once to finish its first-run setup, then re-run this script."
else
  info "Docker present"
fi

info "Creating virtualenv and installing project dependencies"
make setup

info "Done. Next: 'make run' (local) or 'make docker-run' (container)."
