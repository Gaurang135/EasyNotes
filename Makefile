# EasyNotes — one-command workflows
PY := python3.12
VENV := .venv
BIN := $(VENV)/bin
IMAGE := easynotes:local
PORT ?= 8000
DATA_DIR ?= $(PWD)/data

.DEFAULT_GOAL := help

$(VENV)/.installed: requirements.txt requirements-dev.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	touch $@

.PHONY: setup
setup: $(VENV)/.installed ## Create venv and install dependencies

.PHONY: run
run: setup ## Run EasyNotes locally on http://localhost:$(PORT)
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

.PHONY: docker-build
docker-build: ## Build the Docker image ($(IMAGE))
	docker build -t $(IMAGE) .

.PHONY: docker-run
docker-run: docker-build ## Build the image AND run the container locally on :$(PORT)
	docker rm -f easynotes 2>/dev/null || true
	docker run -d --name easynotes -p $(PORT):8000 \
	  -e SNAPSHOT_BACKEND=none \
	  -v easynotes_data:/data \
	  $(IMAGE)
	@echo "EasyNotes running at http://localhost:$(PORT)  (logs: docker logs -f easynotes)"

.PHONY: docker-test
docker-test: docker-build ## Prove the container boots and searches with NO network
	bash tests/test_docker_offline.sh

.PHONY: docker-stop
docker-stop: ## Stop and remove the local container
	docker rm -f easynotes 2>/dev/null || true

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
