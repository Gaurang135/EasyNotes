# EasyNotes — one-command workflows.  Run `make` (or `make help`) to list targets.
#
# ── EDIT ME before `make docker-push` ────────────────────────────────────────
DOCKER_USER ?= CHANGEME          # your Docker Hub username → image is $(DOCKER_USER)/easynotes
# ─────────────────────────────────────────────────────────────────────────────

PY       := python3.12
VENV     := .venv
BIN      := $(VENV)/bin
IMAGE    := easynotes:local
PORT     ?= 8000
DATA_DIR ?= $(PWD)/data

.DEFAULT_GOAL := help

# ═══════════════════════════════ Setup ══════════════════════════════════════
# Sentinel so `make run`/`test` auto-install once, then skip on later runs.
$(VENV)/.installed: requirements.txt requirements-dev.txt scripts/setup.sh
	bash scripts/setup.sh
	touch $@

.PHONY: setup
setup: $(VENV)/.installed ## Create the venv, install deps, bootstrap .env (scripts/setup.sh)

# ════════════════════════════ Local development ═════════════════════════════
.PHONY: run
run: setup ## Run locally with hot reload on :$(PORT) (loads .env if present)
	set -a; [ -f .env ] && . ./.env; set +a; \
	DATA_DIR=$(DATA_DIR) SNAPSHOT_BACKEND=none \
	$(BIN)/uvicorn app.main:app --reload --port $(PORT)

.PHONY: test
test: setup ## Run the full test suite
	$(BIN)/pytest -q

.PHONY: eval
eval: setup ## Print retrieval quality metrics (recall@10, MRR) per mode
	$(BIN)/python -m tests.eval.run

.PHONY: lint
lint: setup ## Lint with ruff
	$(BIN)/ruff check app tests

# ═══════════════════════════════ Docker ═════════════════════════════════════
.PHONY: docker-build
docker-build: ## Build the Docker image ($(IMAGE))
	docker build -t $(IMAGE) .

.PHONY: docker-run
docker-run: docker-build ## Build the image AND run the container locally on :$(PORT)
	docker rm -f easynotes 2>/dev/null || true
	docker run -d --name easynotes -p $(PORT):8000 \
	  -e SNAPSHOT_BACKEND=none \
	  $$([ -f .env ] && echo --env-file .env) \
	  -v easynotes_data:/data \
	  $(IMAGE)
	@echo "EasyNotes running at http://localhost:$(PORT)  (logs: docker logs -f easynotes)"

.PHONY: docker-test
docker-test: docker-build ## Prove the container boots and searches with NO network
	bash tests/test_docker_offline.sh

.PHONY: docker-stop
docker-stop: ## Stop and remove the local container
	docker rm -f easynotes 2>/dev/null || true

# ═══════════════════════════════ Release ════════════════════════════════════
.PHONY: docker-push
docker-push: ## Log in to Docker Hub and push $(DOCKER_USER)/easynotes (:latest + :git-sha)
	DOCKER_USER=$(DOCKER_USER) bash scripts/docker-push.sh

.PHONY: github-push
github-push: ## Push all commits to GitHub (Gaurang135/EasyNotes; override REPO=/BRANCH=/FAST=1)
	bash scripts/github-push.sh

.PHONY: zip
zip: ## Package the project into dist/easynotes.zip (excludes .venv/.env/data; keeps .git)
	bash scripts/package.sh

# ════════════════════════════════ Help ══════════════════════════════════════
.PHONY: help
help: ## Show this help
	@echo "EasyNotes — make targets:"; echo; \
	grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
