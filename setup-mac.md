# EasyNotes — macOS Setup

## One-shot script
```bash
bash scripts/setup-mac.sh
```
This installs Homebrew (if missing), Python 3.12, Docker Desktop (if missing),
then creates the virtualenv and installs dependencies via `make setup`.

> After Docker Desktop installs for the first time, open it once so its engine
> starts, then re-run the script if it asked you to.

## Manual steps (if you prefer)
1. Install Homebrew: https://brew.sh
2. `brew install python@3.12`
3. `brew install --cask docker` and launch Docker Desktop once
4. `make setup`

## Run it
- Local (hot reload): `make run` → http://localhost:8000
- Container (build + deploy locally): `make docker-run` → http://localhost:8000
- Tests: `make test`
- Image only: `make docker-build`
