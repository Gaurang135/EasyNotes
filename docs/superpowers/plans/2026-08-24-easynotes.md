# EasyNotes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build EasyNotes — a single-container, LLM-free FastAPI + SQLite service that ingests mixed-format documents (PDF/DOCX/PPTX/XLSX/CSV/MD/TXT + pasted text) and makes them searchable by keyword, semantic, and hybrid queries, with a similarity-graph UI, deployable durably at $0.

**Architecture:** One FastAPI app. SQLite is the only datastore (FTS5 for keyword/BM25, sqlite-vec for vectors with a numpy brute-force fallback behind one interface). fastembed (bge-small-en-v1.5, ONNX, 384-dim) does embeddings. Ingestion runs in FastAPI BackgroundTasks. Durability on ephemeral free tiers comes from snapshot/restore of the SQLite file to S3-compatible object storage (Cloudflare R2). Retrieval is an importable service shared by `/search`, `/graph?q=`, and a `501` `/answer` LLM slot.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, SQLite (FTS5 + sqlite-vec==0.1.9), fastembed, numpy, pypdf[crypto], python-docx, python-pptx, openpyxl, puremagic, boto3, Cytoscape.js (static, no build step), Docker, Make.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from the design spec (`docs/superpowers/specs/2026-08-23-easynotes-design.md`).

- **LLM-free.** No generation stage. `POST /answer` exists only as a `501` stub.
- **Single writer.** The snapshot/restore design assumes exactly one instance; never scale horizontally.
- **Python 3.12**; Docker base `python:3.12-slim-trixie` (Debian/glibc — **never Alpine**, no musl wheels for onnxruntime/sqlite-vec; **trixie** for SQLite ≥ 3.41).
- **Pin `sqlite-vec==0.1.9`** exactly (delete-path bugs before it, unstable ANN alphas after).
- **vec0 table declared `distance_metric=cosine`** (defaults to L2). Similarity = `1 - cosine_distance`, higher-is-better, converted inside `SqliteVecIndex` and nowhere else.
- **KNN uses `WHERE embedding MATCH :v AND k = :k`** — never `LIMIT`, never joined onto the `MATCH`.
- **sqlite-vec loaded per-connection** in the connection factory; probe catches both `AttributeError` and `sqlite3.OperationalError` and falls back to numpy.
- **Chunk size counted in the model's WordPiece tokenizer**, hard cap 450 (headroom under BGE's 512; fastembed silently truncates at 512).
- **BGE query instruction** `"Represent this sentence for searching relevant passages: "` prepended on the query path only (`embed_query`), never on passages or graph edges.
- **FTS5**: external-content table (`content='chunks', content_rowid='id'`), tokenizer `porter unicode61`, kept in sync by triggers; `ORDER BY rank` (never `bm25() DESC`); user input sanitized before `MATCH`.
- **MIME sniff via `puremagic`** (pure-Python, no libmagic). Reject renamed-zip-as-docx. Enforce decompression-bomb limits on OOXML before parsing.
- **Config via env vars only** (see Task 2 settings). `SNAPSHOT_BACKEND=none` → pure local mode.
- **TDD throughout**: write the failing test, watch it fail, minimal code, watch it pass, commit. Frequent commits.
- **No FastAPI imports inside `app/ingest/`** (no `UploadFile`, `BackgroundTasks`, `Request`). Routes pass plain ids to `pipeline.ingest(document_id)`.
- **Corpus scale target:** hundreds to a few thousand documents.

## Execution phases (task map)

Steel thread first (Tasks 1–10 produce a deployable, searchable app for `.txt`), then breadth.

| # | Task | Deliverable |
|---|---|---|
| 1 | Scaffold, config, `/healthz`, Makefile, setup-mac, DECISIONS, README | `make run` serves health; `make test` green |
| 2 | Data models + error taxonomy | frozen dataclasses importable |
| 3 | DB layer: schema, migrations, connection factory, transactional delete | schema builds; triggers + delete verified |
| 4 | Embedder (Fastembed + Fake) with query/passage split | deterministic fake; query≠passage |
| 5 | VectorIndex (Numpy + Sqlitevec) + factory + **contract suite** | both impls green on one suite |
| 6 | FTS5 keyword index + query sanitizer | sanitizer table-driven tests pass |
| 7 | Chunker (token budget, prose/table, contextual headers) | 512-budget invariant holds |
| 8 | Text/MD parser + registry + validation module | parse txt/md; reject renamed zip |
| 9 | Ingestion pipeline + retrieval service (RRF) + search API | **steel thread**: upload → search via HTTP |
| 10 | Dockerfile + `make docker-build`/`make docker-run` + offline docker test | container searches with `--network none` |
| 11 | PDF parser | encrypted/scanned/owner-password handled |
| 12 | DOCX parser | interleaved order + headings |
| 13 | PPTX parser | slide titles, notes, groups |
| 14 | XLSX parser | read_only, sharedStrings guard |
| 15 | CSV parser | encoding + dialect |
| 16 | Similarity graph (incremental edges) + graph API + export | `/graph`, `/graph?q=`, `/graph/export` |
| 17 | Eval harness (recall@10 + MRR) | `make eval` prints per-mode metrics |
| 18 | Persistence adapter (SnapshotBackend, VACUUM INTO, restore-on-boot) | local round-trip; boot restore |
| 19 | Web UI (upload/paste, search, graph) | manual QA checklist |
| 20 | `501` answer slot + finalize README/DECISIONS | `/answer` returns 501 with instructions |

---

## File Structure

```
easynotes/
├── app/
│   ├── __init__.py
│   ├── main.py               # create_app() composition root + lifespan self-check
│   ├── settings.py           # frozen Settings from env
│   ├── models.py             # frozen dataclasses + Status enum
│   ├── errors.py             # ParseError taxonomy
│   ├── db.py                 # connection factory, schema, migrations, transactional delete
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py           # Depends providers reading app.state
│   │   ├── documents.py      # upload / list / get / delete / paste-text
│   │   ├── search.py         # GET /search
│   │   ├── graph.py          # GET /graph, /graph?q=, /graph/export
│   │   └── answer.py         # POST /answer -> 501
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── validation.py     # size, puremagic sniff, dedup, zip-bomb limits
│   │   ├── chunker.py        # token-budgeted chunking + contextual headers
│   │   ├── pipeline.py       # IngestionPipeline.ingest(document_id)
│   │   └── parsers/
│   │       ├── __init__.py   # PARSERS registry
│   │       ├── text.py  pdf.py  docx.py  pptx.py  xlsx.py  csv.py
│   ├── search/
│   │   ├── __init__.py
│   │   ├── embeddings.py     # Embedder protocol, Fastembed + Fake
│   │   ├── vectors.py        # VectorIndex protocol, Numpy + Sqlitevec, factory
│   │   ├── fts.py            # Fts5Index + sanitizer
│   │   ├── rrf.py            # pure rrf()
│   │   └── service.py        # run_search() shared retrieval
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── edges.py          # incremental similarity-edge compute
│   │   └── export.py         # cytoscape json + graphml serializers
│   └── persistence/
│       ├── __init__.py
│       ├── backends.py       # SnapshotBackend protocol, Local/S3/None
│       └── snapshot.py       # VACUUM INTO snapshot, restore-on-boot, originals sync
├── static/                   # index.html, app.js, styles.css, cytoscape.min.js
├── scripts/
│   ├── setup-mac.sh          # installs Homebrew, python, docker, deps
│   └── bake_model.py         # downloads bge-small-en-v1.5 into the image
├── tests/
│   ├── fixtures/             # tiny committed sample files
│   ├── contracts/            # parametrized VectorIndex contract suite
│   └── eval/                 # queries.jsonl + metrics
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .dockerignore
├── .gitignore
├── setup-mac.md
├── DECISIONS.md
└── README.md
```

---

## Task 1: Scaffold, config, `/healthz`, Makefile, setup-mac, DECISIONS, README

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `.gitignore`, `.dockerignore`
- Create: `Makefile`
- Create: `app/__init__.py`, `app/settings.py`, `app/main.py`
- Create: `tests/__init__.py`, `tests/test_health.py`
- Create: `scripts/setup-mac.sh`, `setup-mac.md`
- Create: `DECISIONS.md`, `README.md`

**Interfaces:**
- Produces: `app.settings.Settings` (frozen dataclass, `Settings.from_env()`); `app.main.create_app(settings: Settings) -> FastAPI`. Later tasks build the composition root inside `create_app`.

- [ ] **Step 1: Write dependency and ignore files**

`requirements.txt`:
```
fastapi==0.115.6
uvicorn[standard]==0.34.0
python-multipart==0.0.20
fastembed==0.5.1
sqlite-vec==0.1.9
numpy==2.2.1
pypdf[crypto]==5.1.0
python-docx==1.1.2
python-pptx==1.0.2
openpyxl==3.1.5
puremagic==1.28
boto3==1.35.90
tokenizers==0.21.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.4
httpx==0.28.1
ruff==0.8.4
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
data/
*.db
*.db-wal
*.db-shm
models/
.pytest_cache/
```

`.dockerignore`:
```
.venv/
data/
tests/
docs/
.git/
__pycache__/
*.pyc
```

- [ ] **Step 2: Write the `Makefile` (all single-command targets the user asked for)**

`Makefile`:
```makefile
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

.PHONY: docker-stop
docker-stop: ## Stop and remove the local container
	docker rm -f easynotes 2>/dev/null || true

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
```

> The three commands the user asked for map to: `make run` (local), `make docker-build` (image only), `make docker-run` (image **and** deploy the container locally). `docker-build`/`docker-run` need the `Dockerfile` from Task 10 — they exist now but only succeed after Task 10.

- [ ] **Step 3: Write the failing health test**

`tests/test_health.py`:
```python
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings


def test_healthz_ok(tmp_path):
    app = create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}))
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 4: Run it to confirm it fails**

Run: `make test`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 5: Write `app/settings.py`**

`app/settings.py`:
```python
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_dir: str = "./data"
    max_upload_mb: int = 25
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_model_path: str | None = None      # baked ONNX dir; enables offline load
    embed_threads: int = 1
    embed_batch_size: int = 16
    snapshot_backend: str = "none"           # none | local | s3
    snapshot_endpoint: str | None = None
    snapshot_bucket: str | None = None
    snapshot_access_key: str | None = None
    snapshot_secret_key: str | None = None
    snapshot_interval_s: int = 300

    @staticmethod
    def from_env(overrides: dict | None = None) -> "Settings":
        env = dict(os.environ)
        if overrides:
            env.update(overrides)
        g = env.get
        return Settings(
            data_dir=g("DATA_DIR", "./data"),
            max_upload_mb=int(g("MAX_UPLOAD_MB", "25")),
            embed_model=g("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
            embed_model_path=g("EMBED_MODEL_PATH") or None,
            embed_threads=int(g("EMBED_THREADS", "1")),
            embed_batch_size=int(g("EMBED_BATCH_SIZE", "16")),
            snapshot_backend=g("SNAPSHOT_BACKEND", "none"),
            snapshot_endpoint=g("SNAPSHOT_ENDPOINT") or None,
            snapshot_bucket=g("SNAPSHOT_BUCKET") or None,
            snapshot_access_key=g("SNAPSHOT_ACCESS_KEY") or None,
            snapshot_secret_key=g("SNAPSHOT_SECRET_KEY") or None,
            snapshot_interval_s=int(g("SNAPSHOT_INTERVAL_S", "300")),
        )
```

- [ ] **Step 6: Write `app/main.py` (minimal composition root)**

`app/main.py`:
```python
from __future__ import annotations
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        # later tasks wire db, embedder, indexes, pipeline, persistence here
        yield

    app = FastAPI(title="EasyNotes", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 7: Run the test to confirm it passes**

Run: `make test`
Expected: PASS (1 passed).

- [ ] **Step 8: Confirm `make run` serves health**

Run: `make run` (then in another shell) `curl -s localhost:8000/healthz`
Expected: `{"status":"ok"}`. Stop with Ctrl-C.

- [ ] **Step 9: Write `scripts/setup-mac.sh` (installs Python, Docker, deps)**

`scripts/setup-mac.sh`:
```bash
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
```

- [ ] **Step 10: Write `setup-mac.md` (the human-readable steps)**

`setup-mac.md`:
```markdown
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
```

- [ ] **Step 11: Write `DECISIONS.md` (seeded from the design)**

`DECISIONS.md`:
```markdown
# EasyNotes — Decision Log

A running log of *why* things are the way they are. Newest first.
Format: date · decision · reason · alternatives rejected.

## 2026-08-24 — Name: EasyNotes
"Dump any file, find it in plain English." Friendly, low-friction feel.
Rejected: Corpora (too academic), Stash/Trove/Shoebox.

## 2026-08-24 — LLM-free (retrieval only)
No generation stage; `POST /answer` is a 501 slot. Reason: zero per-query
cost, fully self-hostable. LLM answer synthesis is a documented extension.

## 2026-08-24 — SQLite as the only store (FTS5 + sqlite-vec)
One file, no DB service to host, free-tier friendly. Rejected: Postgres/
pgvector (that is the deferred "Approach B" rewrite, not v1).

## 2026-08-24 — Vector fallback: numpy behind the VectorIndex interface
sqlite-vec is pre-1.0; a numpy brute-force impl removes it as a hard
dependency. Pinned sqlite-vec==0.1.9 (delete-path bugs elsewhere).

## 2026-08-24 — Hosting: Render free + Cloudflare R2 snapshot/restore ($0)
Render free disk is ephemeral and disks are paid-only; durability via
snapshot/restore to R2 (10GB free, free egress). Rejected: paid Render
disk (~$7.25/mo, simpler but not $0), Turso (gates sqlite-vec to $416/mo).

## 2026-08-24 — 4 protocols only (Parser, VectorIndex, Embedder, SnapshotBackend)
A protocol exists only where there is a second impl or a testing need.
Rejected: Repository/ORM, TaskRunner, AnswerSynthesizer, per-file FileStorage.
```

- [ ] **Step 12: Write `README.md` (skeleton; finalized in Task 20)**

`README.md`:
```markdown
# EasyNotes

Dump any file (PDF, DOCX, PPTX, XLSX, CSV, MD, TXT, or pasted text) and search
it by keyword, natural language, or hybrid — with an interactive similarity
graph of your documents. Runs as one container, fully self-hosted, no LLM, no
per-query cost.

## Quick start
```bash
bash scripts/setup-mac.sh   # first time only
make run                    # http://localhost:8000
```
See `setup-mac.md` for details. Architecture and API docs are filled in as the
build progresses (Task 20).
```

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "feat: project scaffold, config, healthz, Makefile, setup-mac, DECISIONS, README"
```

---

## Task 2: Data models + error taxonomy

**Files:**
- Create: `app/models.py`
- Create: `app/errors.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Status` (str enum: `PENDING/PROCESSING/READY/FAILED`); frozen dataclasses `LocationHint`, `TextBlock`, `ParsedDoc`, `Chunk`, `ScoredChunk`, `SearchHit`, `SearchFilter`, `Document`. Error classes `ParseError` (base), `EncryptedFileError`, `CorruptFileError`, `NoExtractableTextError`, `EmptyDocumentError`, `UnsafeArchiveError`.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
import dataclasses
import pytest
from app.models import TextBlock, ParsedDoc, Chunk, ScoredChunk, Status
from app.errors import ParseError, NoExtractableTextError


def test_textblock_is_frozen():
    b = TextBlock(text="hi", kind="prose", location="page 1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.text = "bye"  # type: ignore


def test_parseddoc_defaults():
    d = ParsedDoc(text_blocks=[], metadata={}, warnings=[])
    assert d.warnings == []


def test_status_values():
    assert Status.READY.value == "ready"


def test_error_hierarchy():
    assert issubclass(NoExtractableTextError, ParseError)


def test_scoredchunk_shape():
    s = ScoredChunk(chunk_id=1, score=0.9)
    assert s.chunk_id == 1 and s.score == 0.9
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/test_models.py -q`
Expected: FAIL — `No module named 'app.models'`.

- [ ] **Step 3: Write `app/errors.py`**

```python
class ParseError(Exception):
    """Base for recoverable parse failures. reason is user-facing."""
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class EncryptedFileError(ParseError): ...
class CorruptFileError(ParseError): ...
class NoExtractableTextError(ParseError): ...
class EmptyDocumentError(ParseError): ...
class UnsafeArchiveError(ParseError): ...
```

- [ ] **Step 4: Write `app/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Sequence


class Status(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


LocationHint = str  # e.g. "page 3", "slide 2", "Sheet1 rows 10-25"


@dataclass(frozen=True)
class TextBlock:
    text: str
    kind: Literal["prose", "table"] = "prose"
    location: LocationHint | None = None
    heading: str | None = None      # section heading path, for contextual headers


@dataclass(frozen=True)
class ParsedDoc:
    text_blocks: list[TextBlock]
    metadata: dict[str, str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    document_id: int
    seq: int
    text: str                       # raw text, for snippets/display
    embed_text: str                 # text actually embedded (may include header)
    location: LocationHint | None = None
    id: int | None = None           # set after DB insert


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: int
    score: float                    # higher-is-better, always


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    document_id: int
    document_title: str
    file_type: str
    snippet: str
    text: str                       # full chunk text (needed by future LLM slot)
    location: LocationHint | None
    score: float


@dataclass(frozen=True)
class SearchFilter:
    file_type: str | None = None
    doc_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass(frozen=True)
class Document:
    id: int
    filename: str
    title: str
    file_type: str
    size: int
    status: Status
    content_hash: str
    uploaded_at: str
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_models.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/errors.py tests/test_models.py
git commit -m "feat: data models and parse-error taxonomy"
```

---

## Task 3: DB layer — schema, migrations, connection factory, transactional delete

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `connect(path: str) -> sqlite3.Connection` — sets WAL, busy_timeout, and loads sqlite-vec per-connection when available; sets `conn.vec_available: bool`.
  - `init_schema(conn)` — idempotent DDL + triggers.
  - `sqlite_vec_available(path) -> bool` — one-shot probe used by the vector factory (Task 5).
  - `delete_document(conn, document_id: int)` — single-transaction cross-table delete.
  - `set_status(conn, document_id, status, error=None, warnings=None)`.
  - `mark_interrupted(conn)` — flips lingering `processing` rows to `failed: interrupted`.

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:
```python
import sqlite3
from app import db
from app.models import Status


def _mk(tmp_path):
    conn = db.connect(str(tmp_path / "e.db"))
    db.init_schema(conn)
    return conn


def test_schema_creates_all_tables(tmp_path):
    conn = _mk(tmp_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"documents", "chunks", "chunks_fts", "similarity_edges", "meta"} <= names


def test_wal_enabled(tmp_path):
    conn = _mk(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_fts_trigger_syncs_on_insert(tmp_path):
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'ready','h','2026-01-01')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (1,1,0,'hello world','hello world')")
    conn.commit()
    rows = conn.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'hello'").fetchall()
    assert rows == [(1,)]


def test_delete_document_clears_all_tables(tmp_path):
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'ready','h','2026-01-01')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (1,1,0,'hello','hello')")
    conn.execute("INSERT INTO similarity_edges(src_chunk_id,dst_chunk_id,score) VALUES (1,2,0.5)")
    conn.commit()
    db.delete_document(conn, 1)
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM similarity_edges").fetchone()[0] == 0
    # FTS integrity must survive the delete
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')")


def test_mark_interrupted(tmp_path):
    conn = _mk(tmp_path)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at) "
                 "VALUES (1,'a.txt','a','txt',3,'processing','h','2026-01-01')")
    conn.commit()
    db.mark_interrupted(conn)
    assert conn.execute("SELECT status FROM documents WHERE id=1").fetchone()[0] == "failed"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/test_db.py -q`
Expected: FAIL — `No module named 'app.db'`.

- [ ] **Step 3: Write `app/db.py`**

```python
from __future__ import annotations
import logging
import sqlite3

log = logging.getLogger("easynotes.db")
EMBED_DIM = 384

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  title TEXT NOT NULL,
  file_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  warnings TEXT,
  content_hash TEXT UNIQUE,
  uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  embed_text TEXT NOT NULL,
  location TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text,
  content='chunks',
  content_rowid='id',
  tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS similarity_edges (
  src_chunk_id INTEGER NOT NULL,
  dst_chunk_id INTEGER NOT NULL,
  score REAL NOT NULL,
  PRIMARY KEY (src_chunk_id, dst_chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON similarity_edges(dst_chunk_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _load_vec(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec into this connection. Returns False on any failure."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except (AttributeError, sqlite3.OperationalError, Exception) as e:  # noqa: BLE001
        log.warning("sqlite-vec unavailable, using numpy fallback: %s", e)
        return False


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.vec_available = _load_vec(conn)  # type: ignore[attr-defined]
    return conn


def sqlite_vec_available(path: str) -> bool:
    ver = sqlite3.sqlite_version_info
    log.info("sqlite runtime version %s", sqlite3.sqlite_version)
    if ver < (3, 41, 0):
        log.warning("SQLite %s < 3.41; sqlite-vec KNN unsupported, using numpy", sqlite3.sqlite_version)
        return False
    c = sqlite3.connect(path)
    ok = _load_vec(c)
    c.close()
    return ok


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if getattr(conn, "vec_available", False):
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, embedding float[{EMBED_DIM}] distance_metric=cosine)"
        )
    conn.commit()


def delete_document(conn: sqlite3.Connection, document_id: int) -> None:
    try:
        conn.execute("BEGIN")
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM chunks WHERE document_id=?", (document_id,))]
        if ids:
            qs = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM similarity_edges WHERE src_chunk_id IN ({qs})", ids)
            conn.execute(f"DELETE FROM similarity_edges WHERE dst_chunk_id IN ({qs})", ids)
            if getattr(conn, "vec_available", False):
                conn.execute(f"DELETE FROM chunk_vectors WHERE chunk_id IN ({qs})", ids)
        conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))  # triggers clean FTS
        conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def set_status(conn, document_id, status, error=None, warnings=None) -> None:
    import json
    conn.execute(
        "UPDATE documents SET status=?, error=?, warnings=? WHERE id=?",
        (status.value if hasattr(status, "value") else status, error,
         json.dumps(warnings or []), document_id),
    )
    conn.commit()


def mark_interrupted(conn) -> None:
    conn.execute(
        "UPDATE documents SET status='failed', error='interrupted' WHERE status='processing'")
    conn.commit()
```

> Note: the `except (... , Exception)` in `_load_vec` is deliberate breadth — the fallback must never crash the app; the failure is logged and numpy takes over.

- [ ] **Step 4: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_db.py -q`
Expected: PASS (5 passed). On a dev Mac without a loadable extension, `chunk_vectors` simply isn't created and the vector tests in Task 5 fall back to numpy — that is expected and logged.

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: sqlite schema, WAL connection factory, FTS triggers, transactional delete"
```

---

## Task 4: Embedder — Fastembed + Fake, with query/passage split

**Files:**
- Create: `app/search/__init__.py`, `app/search/embeddings.py`
- Test: `tests/test_embeddings.py`

**Interfaces:**
- Produces: `Embedder` protocol with `dim: int`, `embed_passages(texts) -> list[list[float]]`, `embed_query(text) -> list[float]`. `FastembedEmbedder(settings)`, `FakeEmbedder(dim=8)`. Constant `BGE_QUERY_INSTRUCTION`.

- [ ] **Step 1: Write the failing test** (uses the fake — real model is exercised only in the Docker test, Task 10)

`tests/test_embeddings.py`:
```python
from app.search.embeddings import FakeEmbedder


def test_fake_is_deterministic_and_right_dim():
    e = FakeEmbedder(dim=8)
    v1 = e.embed_passages(["hello"])[0]
    v2 = e.embed_passages(["hello"])[0]
    assert v1 == v2
    assert len(v1) == 8


def test_query_differs_from_passage_for_same_text():
    e = FakeEmbedder(dim=8)
    q = e.embed_query("hello")
    p = e.embed_passages(["hello"])[0]
    assert q != p  # the query instruction must change the vector
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/test_embeddings.py -q`
Expected: FAIL — import error.

- [ ] **Step 3: Write `app/search/embeddings.py`**

```python
from __future__ import annotations
import hashlib
import math
from typing import Protocol, Sequence, runtime_checkable

BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@runtime_checkable
class Embedder(Protocol):
    dim: int
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """Deterministic hash-based embeddings for tests. No model load."""
    def __init__(self, dim: int = 8):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        raw = [h[i % len(h)] / 255.0 for i in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(BGE_QUERY_INSTRUCTION + text)


class FastembedEmbedder:
    dim = 384

    def __init__(self, settings):
        from fastembed import TextEmbedding
        kwargs = {"threads": settings.embed_threads}
        if settings.embed_model_path:
            kwargs["specific_model_path"] = settings.embed_model_path
        else:
            kwargs["model_name"] = settings.embed_model
        # never pass parallel= : it forks whole model copies (OOM on 512MB)
        self._model = TextEmbedding(**kwargs)
        self._batch = settings.embed_batch_size

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts), batch_size=self._batch)]

    def embed_query(self, text: str) -> list[float]:
        return list(self._model.embed([BGE_QUERY_INSTRUCTION + text]))[0].tolist()
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_embeddings.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/search/__init__.py app/search/embeddings.py tests/test_embeddings.py
git commit -m "feat: embedder protocol with BGE query/passage split + deterministic fake"
```

---

## Task 5: VectorIndex — Numpy + Sqlitevec, factory, and the contract suite

**Files:**
- Create: `app/search/vectors.py`
- Test: `tests/contracts/__init__.py`, `tests/contracts/test_vector_index.py`

**Interfaces:**
- Produces: `VectorIndex` protocol (`add(items)`, `search(vector, k) -> list[ScoredChunk]`, `delete_document(document_id)`); `NumpyVectorIndex(conn)`, `SqliteVecIndex(conn)`; `make_vector_index(conn) -> VectorIndex`.
- Contract: `search` returns cosine **similarity**, higher-is-better; identical vectors → ~1.0, orthogonal → ~0.0.
- Consumes: `app.db` connection; `app.models.ScoredChunk`.

- [ ] **Step 1: Write the failing contract suite (parametrized over BOTH impls)**

`tests/contracts/test_vector_index.py`:
```python
import math
import pytest
from app import db
from app.search.vectors import NumpyVectorIndex, SqliteVecIndex, make_vector_index


def _impls(tmp_path):
    conn = db.connect(str(tmp_path / "v.db"))
    db.init_schema(conn)
    _seed_chunks(conn, [1, 2, 3])
    impls = [("numpy", NumpyVectorIndex(conn))]
    if getattr(conn, "vec_available", False):
        impls.append(("sqlitevec", SqliteVecIndex(conn)))
    return impls


def _seed_chunks(conn, ids):
    conn.execute("INSERT OR IGNORE INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at)"
                 " VALUES (1,'a','a','txt',1,'ready','h','2026')")
    for i in ids:
        conn.execute("INSERT OR IGNORE INTO chunks(id,document_id,seq,text,embed_text) VALUES (?,1,?,'x','x')",
                     (i, i))
    conn.commit()


def _unit(x, y):
    n = math.hypot(x, y)
    return [x / n, y / n] + [0.0] * 382


@pytest.mark.parametrize("name", ["numpy", "sqlitevec"])
def test_identical_and_orthogonal_scores(tmp_path, name):
    for iname, idx in _impls(tmp_path):
        if iname != name:
            continue
        idx.add([(1, _unit(1, 0)), (2, _unit(0, 1))])
        hits = {h.chunk_id: h.score for h in idx.search(_unit(1, 0), k=2)}
        assert hits[1] == pytest.approx(1.0, abs=1e-4)      # identical
        assert hits[2] == pytest.approx(0.0, abs=1e-4)      # orthogonal
        return
    pytest.skip(f"{name} not available on this platform")


@pytest.mark.parametrize("name", ["numpy", "sqlitevec"])
def test_ordering_best_first(tmp_path, name):
    for iname, idx in _impls(tmp_path):
        if iname != name:
            continue
        idx.add([(1, _unit(1, 0)), (2, _unit(1, 1)), (3, _unit(0, 1))])
        order = [h.chunk_id for h in idx.search(_unit(1, 0), k=3)]
        assert order[0] == 1 and order[-1] == 3
        return
    pytest.skip(f"{name} not available")


@pytest.mark.parametrize("name", ["numpy", "sqlitevec"])
def test_churn_delete_then_reinsert(tmp_path, name):
    for iname, idx in _impls(tmp_path):
        if iname != name:
            continue
        idx.add([(1, _unit(1, 0))])
        idx.delete_document(1)                 # removes chunk 1's vector
        _seed_chunks(idx.conn, [4])
        idx.add([(4, _unit(0, 1))])
        ids = [h.chunk_id for h in idx.search(_unit(0, 1), k=5)]
        assert 1 not in ids and 4 in ids
        return
    pytest.skip(f"{name} not available")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/contracts/ -q`
Expected: FAIL — `No module named 'app.search.vectors'`.

- [ ] **Step 3: Write `app/search/vectors.py`**

```python
from __future__ import annotations
from typing import Protocol, Sequence
import numpy as np
from app.models import ScoredChunk


class VectorIndex(Protocol):
    def add(self, items: Sequence[tuple[int, list[float]]]) -> None: ...
    def search(self, vector: list[float], k: int) -> list[ScoredChunk]: ...
    def delete_document(self, document_id: int) -> None: ...


class NumpyVectorIndex:
    """Brute-force cosine over vectors stored in a plain table. Fallback + test default."""
    def __init__(self, conn):
        self.conn = conn
        conn.execute("CREATE TABLE IF NOT EXISTS np_vectors "
                     "(chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
        conn.commit()

    def add(self, items):
        for cid, vec in items:
            arr = np.asarray(vec, dtype=np.float32)  # float32 — never let float64 double memory
            self.conn.execute("INSERT OR REPLACE INTO np_vectors(chunk_id, vec) VALUES (?,?)",
                              (cid, arr.tobytes()))
        self.conn.commit()

    def search(self, vector, k):
        rows = self.conn.execute("SELECT chunk_id, vec FROM np_vectors").fetchall()
        if not rows:
            return []
        q = np.asarray(vector, dtype=np.float32)
        qn = q / (np.linalg.norm(q) or 1.0)
        ids = [r[0] for r in rows]
        mat = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), -1)
        norms = np.linalg.norm(mat, axis=1)
        norms[norms == 0] = 1.0
        sims = (mat @ qn) / norms
        top = np.argsort(-sims)[:k]
        return [ScoredChunk(chunk_id=ids[i], score=float(sims[i])) for i in top]

    def delete_document(self, document_id):
        self.conn.execute(
            "DELETE FROM np_vectors WHERE chunk_id IN "
            "(SELECT id FROM chunks WHERE document_id=?)", (document_id,))
        self.conn.commit()


class SqliteVecIndex:
    """vec0-backed. Cosine distance -> similarity conversion lives ONLY here."""
    def __init__(self, conn):
        self.conn = conn

    def add(self, items):
        import struct
        for cid, vec in items:
            blob = struct.pack("%sf" % len(vec), *vec)
            self.conn.execute("INSERT OR REPLACE INTO chunk_vectors(chunk_id, embedding) VALUES (?,?)",
                              (cid, blob))
        self.conn.commit()

    def search(self, vector, k):
        import struct
        blob = struct.pack("%sf" % len(vector), *vector)
        # k=? form (never LIMIT); no join onto MATCH
        rows = self.conn.execute(
            "SELECT chunk_id, distance FROM chunk_vectors "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (blob, k)).fetchall()
        return [ScoredChunk(chunk_id=cid, score=1.0 - dist) for cid, dist in rows]

    def delete_document(self, document_id):
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM chunks WHERE document_id=?", (document_id,))]
        for cid in ids:
            self.conn.execute("DELETE FROM chunk_vectors WHERE chunk_id=?", (cid,))
        self.conn.commit()


def make_vector_index(conn) -> VectorIndex:
    if getattr(conn, "vec_available", False):
        return SqliteVecIndex(conn)
    return NumpyVectorIndex(conn)
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/contracts/ -q`
Expected: PASS. On a dev Mac without the extension, `sqlitevec` params `skip` and `numpy` passes — that's correct; CI on Linux runs both (see Task 10).

- [ ] **Step 5: Commit**

```bash
git add app/search/vectors.py tests/contracts/
git commit -m "feat: VectorIndex (numpy + sqlite-vec) with parametrized contract suite"
```

---

## Task 6: FTS5 keyword index + query sanitizer

**Files:**
- Create: `app/search/fts.py`
- Test: `tests/test_fts.py`

**Interfaces:**
- Produces: `Fts5Index(conn)` with `search(query, flt, limit, offset) -> list[ScoredChunk]` and `delete_document(document_id)`; module fn `sanitize_fts_query(raw) -> str`. Scores normalized to higher-is-better (`score = -rank`).
- Consumes: `app.db` (chunks_fts populated by triggers); `app.models.ScoredChunk`, `SearchFilter`.

- [ ] **Step 1: Write the failing tests**

`tests/test_fts.py`:
```python
import pytest
from app import db
from app.search.fts import Fts5Index, sanitize_fts_query
from app.models import SearchFilter


@pytest.mark.parametrize("raw", [
    "state-of-the-art", "c++", '"unbalanced', "cats NOT dogs",
    "^cats", "col:term", "?", "",
])
def test_sanitizer_never_raises_and_matches(tmp_path, raw):
    conn = db.connect(str(tmp_path / "f.db"))
    db.init_schema(conn)
    _seed(conn, "the state-of-the-art c++ approach beats cats")
    idx = Fts5Index(conn)
    # must not raise, regardless of input
    idx.search(sanitize_fts_query(raw), SearchFilter(), 10, 0)


def test_bm25_orders_denser_match_first(tmp_path):
    conn = db.connect(str(tmp_path / "f.db"))
    db.init_schema(conn)
    _seed(conn, "cat cat cat", chunk_id=1)
    _seed(conn, "cat dog", chunk_id=2, seq=1)
    idx = Fts5Index(conn)
    order = [h.chunk_id for h in idx.search(sanitize_fts_query("cat"), SearchFilter(), 10, 0)]
    assert order[0] == 1  # denser match ranks first; score higher-is-better
    hits = idx.search(sanitize_fts_query("cat"), SearchFilter(), 10, 0)
    assert hits[0].score >= hits[-1].score


def _seed(conn, text, chunk_id=1, seq=0):
    conn.execute("INSERT OR IGNORE INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at)"
                 " VALUES (1,'a','a','txt',1,'ready','h','2026')")
    conn.execute("INSERT INTO chunks(id,document_id,seq,text,embed_text) VALUES (?,1,?,?,?)",
                 (chunk_id, seq, text, text))
    conn.commit()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/test_fts.py -q`
Expected: FAIL — import error.

- [ ] **Step 3: Write `app/search/fts.py`**

```python
from __future__ import annotations
import re
import sqlite3
from app.models import ScoredChunk, SearchFilter

_TOKEN = re.compile(r'"[^"]*"|\S+')
_KEEP = {"AND", "OR", "NOT", "NEAR"}


def sanitize_fts_query(raw: str) -> str:
    """Make any user string safe for FTS5 MATCH while preserving quoted phrases
    and top-level uppercase boolean operators. Datasette-style."""
    if not raw or not raw.strip():
        return '""'
    out: list[str] = []
    for tok in _TOKEN.findall(raw):
        if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
            inner = tok[1:-1].replace('"', '""')
            if inner.strip():
                out.append(f'"{inner}"')
            continue
        if tok in _KEEP:
            out.append(tok)
            continue
        cleaned = tok.replace('"', '""')
        out.append(f'"{cleaned}"')
    return " ".join(out) or '""'


class Fts5Index:
    def __init__(self, conn):
        self.conn = conn

    def search(self, query: str, flt: SearchFilter, limit: int, offset: int) -> list[ScoredChunk]:
        sql = ("SELECT c.id, rank FROM chunks_fts "
               "JOIN chunks c ON c.id = chunks_fts.rowid "
               "JOIN documents d ON d.id = c.document_id "
               "WHERE chunks_fts MATCH ?")
        params: list = [query]
        if flt.file_type:
            sql += " AND d.file_type = ?"; params.append(flt.file_type)
        if flt.doc_id:
            sql += " AND c.document_id = ?"; params.append(flt.doc_id)
        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params += [limit, offset]
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # last-resort backstop: fully-quoted retry
            params[0] = '"' + query.replace('"', "") + '"'
            rows = self.conn.execute(sql, params).fetchall()
        # bm25 'rank' is negative-is-better; flip to higher-is-better
        return [ScoredChunk(chunk_id=cid, score=-rank) for cid, rank in rows]

    def delete_document(self, document_id: int) -> None:
        # chunks_fts is external-content: deleting chunks rows fires the AFTER DELETE trigger
        self.conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
        self.conn.commit()
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_fts.py -q`
Expected: PASS (9 passed — 8 sanitizer params + 1 ordering).

- [ ] **Step 5: Commit**

```bash
git add app/search/fts.py tests/test_fts.py
git commit -m "feat: FTS5 keyword index with query sanitizer and rank normalization"
```

---

## Task 7: Chunker — token budget, prose/table, contextual headers

**Files:**
- Create: `app/ingest/__init__.py`, `app/ingest/chunker.py`
- Test: `tests/test_chunker.py`, plus fixture `tests/fixtures/wide.csv`

**Interfaces:**
- Produces: `chunk_document(parsed: ParsedDoc, document_id: int, title: str, count_tokens) -> list[Chunk]`; `TokenCounter` (callable `str -> int`); `make_token_counter(settings) -> TokenCounter` (loads the baked tokenizer, falls back to a whitespace×1.6 estimate if unavailable).
- Constant: `MAX_TOKENS = 450`.
- Consumes: `app.models.ParsedDoc`, `TextBlock`, `Chunk`.

- [ ] **Step 1: Create the adversarial fixture**

`tests/fixtures/wide.csv` (numeric-dense — the truncation trap):
```
id,amount,ref,note
1,1234567.89,TXN-000000001,alpha
2,2345678.90,TXN-000000002,bravo
3,3456789.01,TXN-000000003,charlie
```

- [ ] **Step 2: Write the failing tests**

`tests/test_chunker.py`:
```python
from app.models import ParsedDoc, TextBlock
from app.ingest.chunker import chunk_document, MAX_TOKENS


def _count(text):  # deterministic fake counter: 1 token per whitespace word
    return len(text.split())


def test_header_is_prepended_to_embed_text_only():
    parsed = ParsedDoc(text_blocks=[TextBlock(text="body text", kind="prose", heading="Intro")],
                       metadata={}, warnings=[])
    chunks = chunk_document(parsed, document_id=1, title="My Doc", count_tokens=_count)
    assert chunks[0].text == "body text"                      # raw preserved
    assert "My Doc" in chunks[0].embed_text                   # context in embed text
    assert "Intro" in chunks[0].embed_text


def test_every_chunk_under_token_budget():
    big = " ".join(f"word{i}" for i in range(5000))
    parsed = ParsedDoc(text_blocks=[TextBlock(text=big, kind="prose")], metadata={}, warnings=[])
    chunks = chunk_document(parsed, 1, "T", _count)
    assert len(chunks) > 1
    for c in chunks:
        assert _count(c.embed_text) <= MAX_TOKENS


def test_table_rows_split_by_budget_keep_header():
    rows = "\n".join(f"{i},{i*1000},TXN{i}" for i in range(400))
    block = TextBlock(text="id,amount,ref\n" + rows, kind="table", location="rows")
    parsed = ParsedDoc(text_blocks=[block], metadata={}, warnings=[])
    chunks = chunk_document(parsed, 1, "T", _count)
    for c in chunks:
        assert c.embed_text.splitlines()[1].startswith("id,amount,ref") or "id,amount,ref" in c.embed_text
        assert _count(c.embed_text) <= MAX_TOKENS
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/test_chunker.py -q`
Expected: FAIL — import error.

- [ ] **Step 4: Write `app/ingest/chunker.py`**

```python
from __future__ import annotations
from typing import Callable
from app.models import ParsedDoc, TextBlock, Chunk

MAX_TOKENS = 450
OVERLAP_TOKENS = 40
TokenCounter = Callable[[str], int]


def make_token_counter(settings) -> TokenCounter:
    try:
        from tokenizers import Tokenizer
        import os
        path = os.path.join(settings.embed_model_path or "", "tokenizer.json")
        if settings.embed_model_path and os.path.exists(path):
            tok = Tokenizer.from_file(path)
            return lambda t: len(tok.encode(t).ids)
    except Exception:
        pass
    # fallback estimate: wordpiece ~1.6x whitespace words
    return lambda t: int(len(t.split()) * 1.6) + 1


def _header(title: str, heading: str | None) -> str:
    return f"[{title} — {heading}]\n" if heading else f"[{title}]\n"


def _split_words(words: list[str], budget: int, overlap: int, count) -> list[str]:
    out, i = [], 0
    while i < len(words):
        j = i
        while j < len(words) and count(" ".join(words[i:j + 1])) <= budget:
            j += 1
        j = max(j, i + 1)
        out.append(" ".join(words[i:j]))
        if j >= len(words):
            break
        i = max(j - overlap, i + 1)
    return out


def chunk_document(parsed: ParsedDoc, document_id: int, title: str,
                   count_tokens: TokenCounter) -> list[Chunk]:
    chunks: list[Chunk] = []
    seq = 0
    for block in parsed.text_blocks:
        header = _header(title, block.heading)
        budget = MAX_TOKENS - count_tokens(header)
        if block.kind == "table":
            lines = block.text.splitlines()
            head_row, body = (lines[0], lines[1:]) if lines else ("", [])
            group: list[str] = []
            def flush(group):
                nonlocal seq
                if not group:
                    return
                raw = head_row + "\n" + "\n".join(group)
                chunks.append(Chunk(document_id, seq, raw, header + raw, block.location))
                seq += 1
            for row in body:
                trial = head_row + "\n" + "\n".join(group + [row])
                if count_tokens(trial) > budget and group:
                    flush(group); group = [row]
                else:
                    group.append(row)
            flush(group)
        else:
            for piece in _split_words(block.text.split(), budget, OVERLAP_TOKENS, count_tokens):
                chunks.append(Chunk(document_id, seq, piece, header + piece, block.location))
                seq += 1
    return chunks
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_chunker.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add app/ingest/__init__.py app/ingest/chunker.py tests/test_chunker.py tests/fixtures/wide.csv
git commit -m "feat: token-budgeted chunker with contextual headers and table row-grouping"
```

---

## Task 8: Text/MD parser, parser registry, and validation module

**Files:**
- Create: `app/ingest/parsers/__init__.py`, `app/ingest/parsers/text.py`
- Create: `app/ingest/validation.py`
- Test: `tests/test_validation.py`, `tests/test_parser_text.py`
- Fixtures: `tests/fixtures/hello.txt`, `tests/fixtures/notes.md`

**Interfaces:**
- Produces:
  - `Parser` protocol: `file_types: frozenset[str]`, `parse(path) -> ParsedDoc`.
  - `PARSERS: dict[str, Parser]` (registry keyed by canonical file_type, no dot).
  - `app.ingest.validation`: `sniff_type(path, filename) -> str`, `check_size(path, max_mb)`, `content_hash(path) -> str`, `check_archive_safety(path, file_type)` (raises `UnsafeArchiveError`).
- Consumes: `app.models`, `app.errors`.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/hello.txt`:
```
hello world this is a plain text note about payments and refunds
```
`tests/fixtures/notes.md`:
```
# Title

Some **markdown** about invoices.
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parser_text.py`:
```python
from pathlib import Path
from app.ingest.parsers import PARSERS


def test_txt_parser_registered_and_parses():
    p = PARSERS["txt"]
    doc = p.parse(Path("tests/fixtures/hello.txt"))
    assert "payments" in doc.text_blocks[0].text


def test_md_parser_captures_heading():
    p = PARSERS["md"]
    doc = p.parse(Path("tests/fixtures/notes.md"))
    assert any(b.heading == "Title" for b in doc.text_blocks)
```

`tests/test_validation.py`:
```python
import io, zipfile, pytest
from pathlib import Path
from app.ingest import validation
from app.errors import UnsafeArchiveError


def test_sniff_rejects_zip_renamed_as_docx(tmp_path):
    fake = tmp_path / "evil.docx"
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("junk.txt", "not really a docx")
    # a plain zip must NOT be accepted as docx
    assert validation.sniff_type(fake, "evil.docx") != "docx"


def test_content_hash_is_stable(tmp_path):
    f = tmp_path / "a.txt"; f.write_text("abc")
    assert validation.content_hash(f) == validation.content_hash(f)


def test_zip_bomb_ratio_rejected(tmp_path):
    bomb = tmp_path / "b.xlsx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", b"0" * (60 * 1024 * 1024))  # 60MB uncompressed
    with pytest.raises(UnsafeArchiveError):
        validation.check_archive_safety(bomb, "xlsx")
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `.venv/bin/pytest tests/test_validation.py tests/test_parser_text.py -q`
Expected: FAIL — import errors.

- [ ] **Step 4: Write `app/ingest/parsers/text.py`**

```python
from __future__ import annotations
from pathlib import Path
from app.models import ParsedDoc, TextBlock
from app.errors import EmptyDocumentError


class TextParser:
    file_types = frozenset({"txt", "md"})

    def parse(self, path: Path) -> ParsedDoc:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            raise EmptyDocumentError("file is empty")
        blocks: list[TextBlock] = []
        current_heading = None
        buf: list[str] = []

        def flush():
            if buf:
                blocks.append(TextBlock(text="\n".join(buf).strip(),
                                        kind="prose", heading=current_heading))
                buf.clear()

        for line in raw.splitlines():
            if line.startswith("#"):
                flush()
                current_heading = line.lstrip("#").strip()
            else:
                buf.append(line)
        flush()
        if not blocks:
            blocks = [TextBlock(text=raw, kind="prose")]
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
```

- [ ] **Step 5: Write `app/ingest/parsers/__init__.py`**

```python
from __future__ import annotations
from typing import Protocol
from pathlib import Path
from app.models import ParsedDoc
from app.ingest.parsers.text import TextParser


class Parser(Protocol):
    file_types: frozenset[str]
    def parse(self, path: Path) -> ParsedDoc: ...


def _build_registry(*parsers) -> dict[str, "Parser"]:
    reg: dict[str, Parser] = {}
    for p in parsers:
        for ft in p.file_types:
            reg[ft] = p
    return reg


# Parsers for pdf/docx/pptx/xlsx/csv are appended in Tasks 11-15.
PARSERS: dict[str, "Parser"] = _build_registry(TextParser())
```

- [ ] **Step 6: Write `app/ingest/validation.py`**

```python
from __future__ import annotations
import hashlib
import zipfile
from pathlib import Path
from app.errors import UnsafeArchiveError, CorruptFileError

_OOXML = {"docx", "xlsx", "pptx"}
_MAX_UNCOMPRESSED = 250 * 1024 * 1024
_MAX_RATIO = 100
_MAX_ENTRIES = 10_000
_MAX_SHAREDSTRINGS = 50 * 1024 * 1024


def content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def check_size(path: Path, max_mb: int) -> None:
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise CorruptFileError(f"file exceeds {max_mb}MB limit")


def sniff_type(path: Path, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _OOXML:
        # OOXML are zips; confirm the right content type is inside
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
            markers = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}
            if any(n.startswith(markers[ext]) for n in names):
                return ext
            return "zip"  # a plain zip masquerading as OOXML
        except zipfile.BadZipFile:
            return "unknown"
    return ext or "unknown"


def check_archive_safety(path: Path, file_type: str) -> None:
    if file_type not in _OOXML:
        return
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > _MAX_ENTRIES:
                raise UnsafeArchiveError("archive has too many entries")
            total = 0
            for info in infos:
                total += info.file_size
                if info.compress_size and info.file_size / max(info.compress_size, 1) > _MAX_RATIO:
                    raise UnsafeArchiveError("archive compression ratio too high")
                if info.filename.endswith("sharedStrings.xml") and info.file_size > _MAX_SHAREDSTRINGS:
                    raise UnsafeArchiveError("spreadsheet is too text-heavy")
            if total > _MAX_UNCOMPRESSED:
                raise UnsafeArchiveError("archive uncompressed size too large")
    except zipfile.BadZipFile:
        raise CorruptFileError("not a valid office file")
```

- [ ] **Step 7: Run tests to confirm they pass**

Run: `.venv/bin/pytest tests/test_validation.py tests/test_parser_text.py -q`
Expected: PASS (5 passed).

- [ ] **Step 8: Commit**

```bash
git add app/ingest/parsers/ app/ingest/validation.py tests/test_validation.py tests/test_parser_text.py tests/fixtures/hello.txt tests/fixtures/notes.md
git commit -m "feat: text/md parser, parser registry, validation (sniff, dedup, zip-bomb limits)"
```

---

## Task 9: Ingestion pipeline + retrieval service (RRF) + search API — **steel thread**

This task closes the vertical slice: upload a `.txt` over HTTP → it gets parsed, chunked, embedded, indexed → `/search` returns it in all three modes.

**Files:**
- Create: `app/ingest/pipeline.py`, `app/search/rrf.py`, `app/search/service.py`
- Create: `app/api/__init__.py`, `app/api/deps.py`, `app/api/documents.py`, `app/api/search.py`
- Modify: `app/main.py` (wire the composition root)
- Test: `tests/test_rrf.py`, `tests/test_steel_thread.py`

**Interfaces:**
- Produces:
  - `IngestionPipeline(conn, parsers, count_tokens, embedder, vector_index).ingest(document_id: int) -> None`
  - `rrf(rank_lists: list[list[int]], k: int = 60) -> list[tuple[int, float]]`
  - `run_search(conn, embedder, vector_index, fts_index, *, query, mode, flt, limit, offset) -> list[SearchHit]`
  - `create_app(settings, *, embedder=None) -> FastAPI` (embedder override for tests)
- Consumes: everything from Tasks 2–8.

- [ ] **Step 1: Write the failing RRF unit test**

`tests/test_rrf.py`:
```python
from app.search.rrf import rrf


def test_rrf_rewards_agreement():
    # chunk 2 appears high in both lists -> should win
    fused = rrf([[1, 2, 3], [2, 4, 5]], k=60)
    assert fused[0][0] == 2
    ids = [c for c, _ in fused]
    assert set(ids) == {1, 2, 3, 4, 5}


def test_rrf_empty():
    assert rrf([[], []]) == []
```

- [ ] **Step 2: Write the failing steel-thread test**

`tests/test_steel_thread.py`:
```python
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path):
    app = create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                     embedder=FakeEmbedder(dim=32))
    return TestClient(app)


def test_upload_then_search_all_modes(tmp_path):
    c = _client(tmp_path)
    up = c.post("/documents", files={"file": ("note.txt", b"refund policy for late payments", "text/plain")})
    assert up.status_code == 201
    doc_id = up.json()["id"]
    # background task runs synchronously under TestClient
    assert c.get(f"/documents/{doc_id}").json()["status"] == "ready"
    for mode in ("keyword", "semantic", "hybrid"):
        r = c.get("/search", params={"q": "refund", "mode": mode})
        assert r.status_code == 200
        hits = r.json()["results"]
        assert any(h["document_id"] == doc_id for h in hits), mode


def test_paste_text_and_delete(tmp_path):
    c = _client(tmp_path)
    up = c.post("/documents/text", json={"title": "Memo", "text": "quarterly revenue was strong"})
    doc_id = up.json()["id"]
    assert c.get("/search", params={"q": "revenue"}).json()["results"]
    assert c.delete(f"/documents/{doc_id}").status_code == 204
    assert c.get("/search", params={"q": "revenue"}).json()["results"] == []
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `.venv/bin/pytest tests/test_rrf.py tests/test_steel_thread.py -q`
Expected: FAIL — import errors.

- [ ] **Step 4: Write `app/search/rrf.py`**

```python
from __future__ import annotations


def rrf(rank_lists: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Input: per-leg lists of chunk_ids, best-first.
    Output: (chunk_id, score) fused, best-first. No tuning needed; k=60 default."""
    scores: dict[int, float] = {}
    for lst in rank_lists:
        for rank, cid in enumerate(lst):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])
```

- [ ] **Step 5: Write `app/ingest/pipeline.py`**

```python
from __future__ import annotations
import logging
from pathlib import Path
from app import db
from app.models import Status
from app.errors import ParseError
from app.ingest.validation import check_archive_safety

log = logging.getLogger("easynotes.pipeline")


class IngestionPipeline:
    def __init__(self, conn, parsers, count_tokens, embedder, vector_index):
        self.conn = conn
        self.parsers = parsers
        self.count_tokens = count_tokens
        self.embedder = embedder
        self.vector_index = vector_index

    def ingest(self, document_id: int) -> None:
        from app.ingest.chunker import chunk_document
        row = self.conn.execute(
            "SELECT filename, title, file_type FROM documents WHERE id=?",
            (document_id,)).fetchone()
        if not row:
            return
        filename, title, file_type = row
        db.set_status(self.conn, document_id, Status.PROCESSING)
        try:
            parser = self.parsers.get(file_type)
            if parser is None:
                raise ParseError(f"unsupported file type: {file_type}")
            path = Path(self._data_dir()) / "originals" / f"{document_id}_{filename}"
            check_archive_safety(path, file_type)
            parsed = parser.parse(path)
            chunks = chunk_document(parsed, document_id, title, self.count_tokens)
            if not chunks:
                raise ParseError("no extractable text")
            vectors = self.embedder.embed_passages([c.embed_text for c in chunks])
            items = []
            for c, vec in zip(chunks, vectors):
                cur = self.conn.execute(
                    "INSERT INTO chunks(document_id,seq,text,embed_text,location) VALUES (?,?,?,?,?)",
                    (c.document_id, c.seq, c.text, c.embed_text, c.location))
                items.append((cur.lastrowid, vec))
            self.conn.commit()                       # triggers populate FTS
            self.vector_index.add(items)
            db.set_status(self.conn, document_id, Status.READY, warnings=parsed.warnings)
        except ParseError as e:
            db.set_status(self.conn, document_id, Status.FAILED, error=e.reason)
        except Exception as e:                        # never crash the service
            log.exception("ingest failed for %s", document_id)
            db.set_status(self.conn, document_id, Status.FAILED, error=f"internal error: {e}")

    def _data_dir(self) -> str:
        return self.conn.execute("SELECT value FROM meta WHERE key='data_dir'").fetchone()[0]
```

- [ ] **Step 6: Write `app/search/service.py`**

```python
from __future__ import annotations
from app.models import SearchHit, SearchFilter
from app.search.fts import sanitize_fts_query
from app.search.rrf import rrf

FUSION_DEPTH = 100


def _passes_filter(conn, chunk_ids, flt: SearchFilter):
    if not chunk_ids or (not flt.file_type and not flt.doc_id):
        return set(chunk_ids)
    qs = ",".join("?" * len(chunk_ids))
    sql = (f"SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id "
           f"WHERE c.id IN ({qs})")
    params = list(chunk_ids)
    if flt.file_type:
        sql += " AND d.file_type=?"; params.append(flt.file_type)
    if flt.doc_id:
        sql += " AND c.document_id=?"; params.append(flt.doc_id)
    return {r[0] for r in conn.execute(sql, params)}


def _snippet(text: str, query: str, width: int = 200) -> str:
    low = text.lower()
    for term in query.lower().split():
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 2)
            return ("…" if start else "") + text[start:start + width].strip() + "…"
    return text[:width].strip() + ("…" if len(text) > width else "")


def _hydrate(conn, ordered_ids, scores, query) -> list[SearchHit]:
    hits = []
    for cid in ordered_ids:
        row = conn.execute(
            "SELECT c.document_id, d.title, d.file_type, c.text, c.location "
            "FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=?",
            (cid,)).fetchone()
        if not row:
            continue
        doc_id, title, ftype, text, loc = row
        hits.append(SearchHit(chunk_id=cid, document_id=doc_id, document_title=title,
                              file_type=ftype, snippet=_snippet(text, query),
                              text=text, location=loc, score=scores.get(cid, 0.0)))
    return hits


def run_search(conn, embedder, vector_index, fts_index, *, query, mode, flt, limit, offset):
    if mode == "keyword":
        scored = fts_index.search(sanitize_fts_query(query), flt, FUSION_DEPTH, 0)
        ordered = [s.chunk_id for s in scored]
        scores = {s.chunk_id: s.score for s in scored}
    elif mode == "semantic":
        qv = embedder.embed_query(query)
        scored = vector_index.search(qv, FUSION_DEPTH)
        allowed = _passes_filter(conn, [s.chunk_id for s in scored], flt)
        scored = [s for s in scored if s.chunk_id in allowed]
        ordered = [s.chunk_id for s in scored]
        scores = {s.chunk_id: s.score for s in scored}
    else:  # hybrid
        kw = fts_index.search(sanitize_fts_query(query), flt, FUSION_DEPTH, 0)
        qv = embedder.embed_query(query)
        sem = vector_index.search(qv, FUSION_DEPTH)
        allowed = _passes_filter(conn, [s.chunk_id for s in sem], flt)
        sem = [s for s in sem if s.chunk_id in allowed]
        fused = rrf([[s.chunk_id for s in kw], [s.chunk_id for s in sem]])
        ordered = [cid for cid, _ in fused]
        scores = dict(fused)
    page = ordered[offset:offset + limit]
    return _hydrate(conn, page, scores, query)
```

- [ ] **Step 7: Write `app/api/deps.py`, `app/api/documents.py`, `app/api/search.py`**

`app/api/__init__.py`: *(empty)*

`app/api/deps.py`:
```python
from fastapi import Request


def get_state(request: Request):
    return request.app.state
```

`app/api/documents.py`:
```python
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from app import db
from app.models import Status
from app.ingest import validation
from app.api.deps import get_state

router = APIRouter()


class PasteText(BaseModel):
    title: str
    text: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_row(state, filename, title, file_type, size, chash) -> int:
    cur = state.conn.execute(
        "INSERT INTO documents(filename,title,file_type,size,status,content_hash,uploaded_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (filename, title, file_type, size, Status.PENDING.value, chash, _now()))
    state.conn.commit()
    return cur.lastrowid


@router.post("/documents", status_code=201)
def upload(background: BackgroundTasks, file: UploadFile = File(...), state=Depends(get_state)):
    originals = Path(state.settings.data_dir) / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    tmp = originals / f"_tmp_{file.filename}"
    tmp.write_bytes(file.file.read())
    validation.check_size(tmp, state.settings.max_upload_mb)
    ftype = validation.sniff_type(tmp, file.filename or "")
    if ftype not in state.parsers:
        tmp.unlink(missing_ok=True)
        raise HTTPException(415, f"unsupported file type: {ftype}")
    chash = validation.content_hash(tmp)
    existing = state.conn.execute("SELECT id FROM documents WHERE content_hash=?", (chash,)).fetchone()
    if existing:
        tmp.unlink(missing_ok=True)
        return {"id": existing[0], "status": "duplicate"}
    title = (file.filename or "untitled").rsplit(".", 1)[0]
    doc_id = _create_row(state, file.filename, title, ftype, tmp.stat().st_size, chash)
    tmp.rename(originals / f"{doc_id}_{file.filename}")
    background.add_task(state.pipeline.ingest, doc_id)
    return {"id": doc_id, "status": "pending"}


@router.post("/documents/text", status_code=201)
def paste(body: PasteText, background: BackgroundTasks, state=Depends(get_state)):
    originals = Path(state.settings.data_dir) / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    data = body.text.encode()
    import hashlib
    chash = hashlib.sha256(data).hexdigest()
    existing = state.conn.execute("SELECT id FROM documents WHERE content_hash=?", (chash,)).fetchone()
    if existing:
        return {"id": existing[0], "status": "duplicate"}
    doc_id = _create_row(state, f"{body.title}.txt", body.title, "txt", len(data), chash)
    (originals / f"{doc_id}_{body.title}.txt").write_bytes(data)
    background.add_task(state.pipeline.ingest, doc_id)
    return {"id": doc_id, "status": "pending"}


@router.get("/documents")
def list_docs(state=Depends(get_state)):
    rows = state.conn.execute(
        "SELECT id,title,file_type,status,error,uploaded_at FROM documents ORDER BY id DESC").fetchall()
    return [{"id": r[0], "title": r[1], "file_type": r[2], "status": r[3],
             "error": r[4], "uploaded_at": r[5]} for r in rows]


@router.get("/documents/{doc_id}")
def get_doc(doc_id: int, state=Depends(get_state)):
    r = state.conn.execute(
        "SELECT id,title,file_type,status,error,warnings FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    return {"id": r[0], "title": r[1], "file_type": r[2], "status": r[3],
            "error": r[4], "warnings": json.loads(r[5] or "[]")}


@router.delete("/documents/{doc_id}", status_code=204)
def delete_doc(doc_id: int, state=Depends(get_state)):
    db.delete_document(state.conn, doc_id)
    return None
```

`app/api/search.py`:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from app.models import SearchFilter
from app.search.service import run_search
from app.api.deps import get_state

router = APIRouter()


@router.get("/search")
def search(q: str, mode: str = "hybrid", type: str | None = None, doc_id: int | None = None,
           limit: int = 20, offset: int = 0, state=Depends(get_state)):
    flt = SearchFilter(file_type=type, doc_id=doc_id)
    hits = run_search(state.conn, state.embedder, state.vector_index, state.fts_index,
                      query=q, mode=mode, flt=flt, limit=limit, offset=offset)
    return {"query": q, "mode": mode, "results": [
        {"chunk_id": h.chunk_id, "document_id": h.document_id, "document_title": h.document_title,
         "file_type": h.file_type, "snippet": h.snippet, "location": h.location,
         "score": h.score} for h in hits]}
```

- [ ] **Step 8: Rewrite `app/main.py` composition root**

```python
from __future__ import annotations
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.settings import Settings
from app import db
from app.ingest.parsers import PARSERS
from app.ingest.chunker import make_token_counter
from app.ingest.pipeline import IngestionPipeline
from app.search.vectors import make_vector_index
from app.search.fts import Fts5Index
from app.search.embeddings import FastembedEmbedder
from app.api import documents, search


def create_app(settings: Settings | None = None, *, embedder=None) -> FastAPI:
    settings = settings or Settings.from_env()
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.connect(str(data_dir / "easynotes.db"))
        db.init_schema(conn)
        db.mark_interrupted(conn)
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('data_dir',?)",
                     (str(data_dir),))
        conn.commit()
        app.state.settings = settings
        app.state.conn = conn
        app.state.parsers = PARSERS
        app.state.embedder = embedder or FastembedEmbedder(settings)
        app.state.vector_index = make_vector_index(conn)
        app.state.fts_index = Fts5Index(conn)
        app.state.pipeline = IngestionPipeline(
            conn, PARSERS, make_token_counter(settings),
            app.state.embedder, app.state.vector_index)
        yield
        conn.close()

    app = FastAPI(title="EasyNotes", lifespan=lifespan)
    app.include_router(documents.router)
    app.include_router(search.router)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 9: Run all tests to confirm they pass**

Run: `make test`
Expected: PASS (all prior tests + `test_rrf.py` 2 + `test_steel_thread.py` 2). The steel thread now works end-to-end over HTTP with the fake embedder.

- [ ] **Step 10: Manually verify with the real model**

Run: `make run`, then:
```bash
curl -s -F "file=@tests/fixtures/hello.txt" localhost:8000/documents
curl -s "localhost:8000/search?q=refunds&mode=hybrid"
```
Expected: the second call returns the note (first call downloads the model on first run — that is the only time the local dev server needs the network; the Docker image bakes it, Task 10).

- [ ] **Step 11: Commit**

```bash
git add app/ingest/pipeline.py app/search/rrf.py app/search/service.py app/api/ app/main.py tests/test_rrf.py tests/test_steel_thread.py
git commit -m "feat: ingestion pipeline + RRF hybrid retrieval service + documents/search API (steel thread)"
```

---

## Task 10: Dockerfile, model baking, `make docker-build`/`make docker-run`, offline steel-thread test

This makes EasyNotes a self-contained image that boots with **no network** (the promise the steel thread must prove).

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `scripts/bake_model.py`
- Test: `tests/test_docker_offline.sh` (run via `make docker-test`)
- Modify: `Makefile` (add `docker-test`)

**Interfaces:**
- Produces: image `easynotes:local`; container serving `:8000` with `EMBED_MODEL_PATH` baked and `SNAPSHOT_BACKEND=none`.

- [ ] **Step 1: Write `scripts/bake_model.py`**

```python
"""Download bge-small-en-v1.5 into the image at build time, then print its path."""
import sys
from fastembed import TextEmbedding

DEST = "/app/models"
m = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_dir=DEST)
# force a real embed so all files are materialized
list(m.embed(["warmup"]))
print(f"model cached under {DEST}", file=sys.stderr)
```

- [ ] **Step 2: Write the `Dockerfile`**

```dockerfile
# Debian/glibc (never Alpine — no musl wheels for onnxruntime/sqlite-vec).
# trixie ships SQLite >= 3.46 so sqlite-vec KNN works.
FROM python:3.12-slim-trixie

# UID-1000 non-root user (works on HF Spaces and everywhere else)
RUN useradd -m -u 1000 app
ENV HOME=/home/app \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    SNAPSHOT_BACKEND=none

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image, owned by the runtime user
COPY scripts/bake_model.py scripts/bake_model.py
RUN python scripts/bake_model.py && \
    EMBED_DIR="$(find /app/models -name model_optimized.onnx -o -name model.onnx | head -1 | xargs dirname)" && \
    echo "EMBED_MODEL_PATH=$EMBED_DIR" > /app/.env.model
ENV EMBED_MODEL_PATH=/app/models

COPY app/ app/
COPY static/ static/
RUN mkdir -p /data && chown -R app:app /app /data
USER app

EXPOSE 8000
# resolve the exact baked model dir at start, then launch
CMD ["sh", "-c", "export EMBED_MODEL_PATH=$(find /app/models -type d -name '*bge-small-en*' | head -1); exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

> The `EMBED_MODEL_PATH` glob is defensive: fastembed's cache layout is versioned, so the exact directory is discovered at boot rather than hard-coded. `FastembedEmbedder` passes `specific_model_path`, so no network is touched at runtime.

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  easynotes:
    build: .
    image: easynotes:local
    ports:
      - "${PORT:-8000}:8000"
    environment:
      SNAPSHOT_BACKEND: "none"
    volumes:
      - easynotes_data:/data
volumes:
  easynotes_data:
```

- [ ] **Step 4: Add the offline test to the Makefile and write the script**

Append to `Makefile`:
```makefile
.PHONY: docker-test
docker-test: docker-build ## Prove the container boots and searches with NO network
	bash tests/test_docker_offline.sh
```

`tests/test_docker_offline.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
docker rm -f easynotes_test 2>/dev/null || true
# --network none proves the offline-boot promise
docker run -d --name easynotes_test --network none -e SNAPSHOT_BACKEND=none easynotes:local
cleanup() { docker rm -f easynotes_test >/dev/null 2>&1 || true; }
trap cleanup EXIT
echo "waiting for boot (offline)…"
for i in $(seq 1 30); do
  if docker exec easynotes_test python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)" 2>/dev/null; then
    ok=1; break
  fi
  sleep 2
done
[ "${ok:-0}" = 1 ] || { echo "FAIL: did not become healthy offline"; docker logs easynotes_test; exit 1; }
# ingest + search entirely inside the offline container
docker exec easynotes_test sh -c '
  printf "refund policy for late payments" > /tmp/n.txt
  python - <<PY
import urllib.request, json
b=open("/tmp/n.txt","rb").read()
# multipart by hand
boundary="X"
body=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"n.txt\"\r\nContent-Type: text/plain\r\n\r\n").encode()+b+f"\r\n--{boundary}--\r\n".encode()
req=urllib.request.Request("http://localhost:8000/documents",data=body,headers={"Content-Type":f"multipart/form-data; boundary={boundary}"})
print(urllib.request.urlopen(req).read().decode())
PY'
sleep 3
docker exec easynotes_test python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/search?q=refund&mode=hybrid').read().decode())" | grep -q refund \
  && echo "PASS: offline ingest + search works" || { echo "FAIL: search returned nothing"; exit 1; }
```

- [ ] **Step 5: Build the image**

Run: `make docker-build`
Expected: image builds; the `bake_model.py` step downloads the model once during build.

- [ ] **Step 6: Run the offline proof**

Run: `make docker-test`
Expected: `PASS: offline ingest + search works`. This is the steel-thread proof — the container ingests and searches a document with `--network none`.

- [ ] **Step 7: Verify the two user-facing docker commands**

Run: `make docker-run`
Expected: prints `EasyNotes running at http://localhost:8000`; `curl localhost:8000/healthz` → ok. Stop with `make docker-stop`.

- [ ] **Step 8: Commit**

```bash
git add Dockerfile docker-compose.yml scripts/bake_model.py tests/test_docker_offline.sh Makefile
git commit -m "feat: offline-capable Docker image + docker-build/run/test targets (steel thread proven in-container)"
```

> **Milestone:** Tasks 1–10 deliver a deployable, searchable EasyNotes for `.txt`/`.md`. Everything after this adds breadth on the same spine.

---

## Tasks 11–15: Format parsers (one per commit)

Each parser is a new module + one registry line + fixtures + one test. They share the shape from Task 8. **Pattern for every parser task:** (1) add the fixture, (2) write the failing test, (3) write the parser, (4) register it in `app/ingest/parsers/__init__.py` by adding it to the `_build_registry(...)` call, (5) run tests, (6) commit.

### Task 11: PDF parser (`app/ingest/parsers/pdf.py`)

**Files:** Create `app/ingest/parsers/pdf.py`; Modify `app/ingest/parsers/__init__.py`; Test `tests/test_parser_pdf.py`; Fixtures `tests/fixtures/simple.pdf`, `tests/fixtures/owner_locked.pdf` (owner-password only), `tests/fixtures/user_locked.pdf` (user password).

- [ ] **Step 1: Test**
```python
from pathlib import Path
import pytest
from app.ingest.parsers.pdf import PdfParser
from app.errors import EncryptedFileError, NoExtractableTextError


def test_pdf_extracts_text():
    doc = PdfParser().parse(Path("tests/fixtures/simple.pdf"))
    assert doc.text_blocks and doc.text_blocks[0].location == "page 1"


def test_owner_password_pdf_still_parses():
    # empty user password -> must NOT be treated as encrypted
    doc = PdfParser().parse(Path("tests/fixtures/owner_locked.pdf"))
    assert doc.text_blocks


def test_user_password_pdf_raises_encrypted():
    with pytest.raises(EncryptedFileError):
        PdfParser().parse(Path("tests/fixtures/user_locked.pdf"))
```

- [ ] **Step 2: Implementation**
```python
from __future__ import annotations
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from app.models import ParsedDoc, TextBlock
from app.errors import EncryptedFileError, CorruptFileError, NoExtractableTextError


class PdfParser:
    file_types = frozenset({"pdf"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                # owner-password-only PDFs decrypt with an empty user password
                if reader.decrypt("") == 0:
                    raise EncryptedFileError("PDF requires a password")
            blocks, warnings = [], []
            for i, page in enumerate(reader.pages):
                try:
                    text = (page.extract_text() or "").strip()
                except Exception:
                    warnings.append(f"page {i+1}: extraction failed"); continue
                if text:
                    blocks.append(TextBlock(text=text, kind="prose", location=f"page {i+1}"))
            if not blocks:
                raise NoExtractableTextError("no extractable text (needs OCR)")
            return ParsedDoc(text_blocks=blocks, metadata={}, warnings=warnings)
        except (PdfReadError, OSError) as e:
            raise CorruptFileError(f"unreadable PDF: {e}")
```

- [ ] **Step 3: Register** — in `__init__.py`, `from app.ingest.parsers.pdf import PdfParser` and add `PdfParser()` to `_build_registry(...)`.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_parser_pdf.py -q` → PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: PDF parser (owner-password handling, per-page warnings, scanned detection)"`

### Task 12: DOCX parser (`app/ingest/parsers/docx.py`)

**Files:** Create `docx.py`; Modify registry; Test `tests/test_parser_docx.py`; Fixture `tests/fixtures/sample.docx` (with a Heading 1 and a table).

- [ ] **Step 1: Test**
```python
from pathlib import Path
from app.ingest.parsers.docx import DocxParser


def test_docx_preserves_order_and_headings():
    doc = DocxParser().parse(Path("tests/fixtures/sample.docx"))
    assert any(b.heading for b in doc.text_blocks)
    assert any(b.kind == "table" for b in doc.text_blocks)
```

- [ ] **Step 2: Implementation** (requires `python-docx >= 1.1` for `iter_inner_content`)
```python
from __future__ import annotations
from pathlib import Path
from docx import Document as Docx
from docx.text.paragraph import Paragraph
from docx.table import Table
from app.models import ParsedDoc, TextBlock
from app.errors import CorruptFileError, NoExtractableTextError


class DocxParser:
    file_types = frozenset({"docx"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            d = Docx(str(path))
        except Exception as e:
            raise CorruptFileError(f"unreadable DOCX: {e}")
        blocks: list[TextBlock] = []
        heading = None
        for item in d.iter_inner_content():          # preserves interleaved order
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                if item.style and item.style.name and item.style.name.startswith("Heading"):
                    heading = text
                    blocks.append(TextBlock(text=text, kind="prose", heading=heading))
                else:
                    blocks.append(TextBlock(text=text, kind="prose", heading=heading))
            elif isinstance(item, Table):
                rows = ["\t".join(c.text for c in row.cells) for row in item.rows]
                if rows:
                    blocks.append(TextBlock(text="\n".join(rows), kind="table", heading=heading))
        if not blocks:
            raise NoExtractableTextError("no extractable text")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
```

- [ ] **Steps 3–5:** register, run `tests/test_parser_docx.py` → PASS, commit `"feat: DOCX parser (interleaved order, headings, tables)"`.

### Task 13: PPTX parser (`app/ingest/parsers/pptx.py`)

**Files:** Create `pptx.py`; Modify registry; Test `tests/test_parser_pptx.py`; Fixture `tests/fixtures/sample.pptx` (title + body + a grouped shape + speaker notes).

- [ ] **Step 1: Test**
```python
from pathlib import Path
from app.ingest.parsers.pptx import PptxParser


def test_pptx_reads_titles_body_and_notes():
    doc = PptxParser().parse(Path("tests/fixtures/sample.pptx"))
    assert any(b.location and b.location.startswith("slide 1") for b in doc.text_blocks)
    joined = " ".join(b.text for b in doc.text_blocks)
    assert "notes" in joined.lower()
```

- [ ] **Step 2: Implementation**
```python
from __future__ import annotations
from pathlib import Path
from pptx import Presentation
from app.models import ParsedDoc, TextBlock
from app.errors import CorruptFileError, NoExtractableTextError


def _iter_text(shapes):
    for shape in shapes:
        if shape.shape_type == 6:  # GROUP — recurse
            yield from _iter_text(shape.shapes)
        elif shape.has_text_frame:
            t = shape.text_frame.text.strip()
            if t:
                yield t


class PptxParser:
    file_types = frozenset({"pptx"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            prs = Presentation(str(path))
        except Exception as e:
            raise CorruptFileError(f"unreadable PPTX: {e}")
        blocks: list[TextBlock] = []
        for i, slide in enumerate(prs.slides, 1):
            title = slide.shapes.title.text.strip() if slide.shapes.title else None
            body = list(_iter_text(slide.shapes))
            if body:
                blocks.append(TextBlock(text="\n".join(body), kind="prose",
                                        location=f"slide {i}", heading=title))
            # notes: access .notes_slide only if present (accessing it CREATES one)
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    blocks.append(TextBlock(text=notes, kind="prose",
                                            location=f"slide {i} notes", heading=title))
        if not blocks:
            raise NoExtractableTextError("no extractable text")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
```

- [ ] **Steps 3–5:** register, run → PASS, commit `"feat: PPTX parser (titles, groups, notes without side effects)"`.

### Task 14: XLSX parser (`app/ingest/parsers/xlsx.py`)

**Files:** Create `xlsx.py`; Modify registry; Test `tests/test_parser_xlsx.py`; Fixture `tests/fixtures/sample.xlsx` (one sheet, a header row + data, a formula cell).

- [ ] **Step 1: Test**
```python
from pathlib import Path
from app.ingest.parsers.xlsx import XlsxParser


def test_xlsx_emits_table_block_with_sheet_location():
    doc = XlsxParser().parse(Path("tests/fixtures/sample.xlsx"))
    tb = doc.text_blocks[0]
    assert tb.kind == "table"
    assert tb.location and "Sheet" in tb.location
```

- [ ] **Step 2: Implementation** (read_only + data_only; explicit close)
```python
from __future__ import annotations
from pathlib import Path
from openpyxl import load_workbook
from app.models import ParsedDoc, TextBlock
from app.errors import CorruptFileError, NoExtractableTextError


class XlsxParser:
    file_types = frozenset({"xlsx"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            wb = load_workbook(str(path), read_only=True, data_only=True)
        except Exception as e:
            raise CorruptFileError(f"unreadable XLSX: {e}")
        blocks: list[TextBlock] = []
        try:
            for ws in wb.worksheets:
                rows = []
                for row in ws.iter_rows(values_only=True):
                    cells = ["" if v is None else str(v) for v in row]
                    if any(cells):
                        rows.append(",".join(cells))
                if rows:
                    blocks.append(TextBlock(text="\n".join(rows), kind="table",
                                            location=f"{ws.title} rows 1-{len(rows)}"))
        finally:
            wb.close()
        if not blocks:
            raise NoExtractableTextError("spreadsheet has no data")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
```

- [ ] **Steps 3–5:** register, run → PASS, commit `"feat: XLSX parser (read_only, data_only, per-sheet table blocks)"`.

### Task 15: CSV parser (`app/ingest/parsers/csv.py`)

**Files:** Create `csv.py`; Modify registry; Test `tests/test_parser_csv.py`; Fixture reuse `tests/fixtures/wide.csv`.

- [ ] **Step 1: Test**
```python
from pathlib import Path
from app.ingest.parsers.csv import CsvParser


def test_csv_is_table_block():
    doc = CsvParser().parse(Path("tests/fixtures/wide.csv"))
    assert doc.text_blocks[0].kind == "table"
    assert "amount" in doc.text_blocks[0].text
```

- [ ] **Step 2: Implementation** (utf-8-sig first; dialect sniff as a hint)
```python
from __future__ import annotations
import csv as _csv
from pathlib import Path
from app.models import ParsedDoc, TextBlock
from app.errors import EmptyDocumentError


class CsvParser:
    file_types = frozenset({"csv"})

    def parse(self, path: Path) -> ParsedDoc:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        if not raw.strip():
            raise EmptyDocumentError("file is empty")
        try:
            dialect = _csv.Sniffer().sniff(raw[:2048], delimiters=",;\t|")
        except _csv.Error:
            dialect = _csv.excel
        rows = [",".join(r) for r in _csv.reader(raw.splitlines(), dialect)]
        return ParsedDoc(text_blocks=[TextBlock(text="\n".join(rows), kind="table",
                                                location="rows")], metadata={}, warnings=[])
```

- [ ] **Steps 3–5:** register, run → PASS, commit `"feat: CSV parser (encoding + dialect sniff)"`.

> After Task 15, `make test` runs the full parser suite and `make docker-test` still passes. All seven formats now ingest.

---

## Task 16: Similarity graph — incremental edges, export, graph API

**Files:**
- Create: `app/graph/__init__.py`, `app/graph/edges.py`, `app/graph/export.py`, `app/api/graph.py`
- Modify: `app/ingest/pipeline.py` (compute edges after a doc goes ready), `app/main.py` (register graph router)
- Test: `tests/test_graph.py`

**Interfaces:**
- Produces:
  - `compute_edges_for_document(conn, vector_index, document_id, top_k=5) -> None` — cross-document neighbors only; prunes replaced edges; idempotent.
  - `to_cytoscape(conn, matched: dict[int,float] | None) -> dict`, `to_graphml(conn) -> str`.
  - `GET /graph`, `GET /graph?q=`, `GET /graph/export`.

- [ ] **Step 1: Write the failing test**
```python
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def _client(tmp_path):
    return TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                                 embedder=FakeEmbedder(dim=32)))


def test_graph_has_nodes_and_cross_doc_edges(tmp_path):
    c = _client(tmp_path)
    c.post("/documents/text", json={"title": "A", "text": "refund policy for payments and chargebacks"})
    c.post("/documents/text", json={"title": "B", "text": "payment refund and chargeback handling"})
    g = c.get("/graph").json()
    assert len(g["nodes"]) >= 2
    # edges must connect different documents only
    for e in g["edges"]:
        assert e["data"]["source_doc"] != e["data"]["target_doc"]


def test_graph_query_marks_matches(tmp_path):
    c = _client(tmp_path)
    c.post("/documents/text", json={"title": "A", "text": "refund policy"})
    g = c.get("/graph", params={"q": "refund"}).json()
    assert any(n["data"].get("matched") for n in g["nodes"])
```

- [ ] **Step 2: Run it** → FAIL (import/route missing).

- [ ] **Step 3: Write `app/graph/edges.py`**
```python
from __future__ import annotations

EDGE_TOP_K = 5
EDGE_FLOOR = 0.35   # calibrated floor so unrelated docs don't all connect


def compute_edges_for_document(conn, vector_index, document_id: int, top_k: int = EDGE_TOP_K) -> None:
    chunk_ids = [r[0] for r in conn.execute(
        "SELECT id FROM chunks WHERE document_id=?", (document_id,))]
    for cid in chunk_ids:
        vec = _vector_for(conn, vector_index, cid)
        if vec is None:
            continue
        for sc in vector_index.search(vec, top_k + 10):
            if sc.chunk_id == cid or sc.score < EDGE_FLOOR:
                continue
            other_doc = conn.execute("SELECT document_id FROM chunks WHERE id=?",
                                     (sc.chunk_id,)).fetchone()
            if not other_doc or other_doc[0] == document_id:
                continue                       # cross-document edges only
            a, b = sorted((cid, sc.chunk_id))
            conn.execute("INSERT OR REPLACE INTO similarity_edges(src_chunk_id,dst_chunk_id,score) "
                         "VALUES (?,?,?)", (a, b, sc.score))
    conn.commit()


def _vector_for(conn, vector_index, chunk_id):
    # NumpyVectorIndex stores in np_vectors; SqliteVecIndex in chunk_vectors
    row = conn.execute("SELECT vec FROM np_vectors WHERE chunk_id=?", (chunk_id,)).fetchone() \
        if _has_table(conn, "np_vectors") else None
    if row:
        import numpy as np
        return np.frombuffer(row[0], dtype=np.float32).tolist()
    if _has_table(conn, "chunk_vectors"):
        r = conn.execute("SELECT embedding FROM chunk_vectors WHERE chunk_id=?", (chunk_id,)).fetchone()
        if r:
            import struct
            return list(struct.unpack("%sf" % (len(r[0]) // 4), r[0]))
    return None


def _has_table(conn, name) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
```

- [ ] **Step 4: Write `app/graph/export.py`**
```python
from __future__ import annotations
import xml.sax.saxutils as sx

_COLORS = {"pdf": "#e2504a", "docx": "#2b579a", "pptx": "#d24726", "xlsx": "#217346",
           "csv": "#4c9a2a", "md": "#555", "txt": "#888"}


def _doc_nodes(conn, matched):
    rows = conn.execute(
        "SELECT d.id, d.title, d.file_type, count(c.id) "
        "FROM documents d LEFT JOIN chunks c ON c.document_id=d.id "
        "WHERE d.status='ready' GROUP BY d.id").fetchall()
    nodes = []
    matched = matched or {}
    matched_docs = {}
    if matched:
        for cid, score in matched.items():
            r = conn.execute("SELECT document_id FROM chunks WHERE id=?", (cid,)).fetchone()
            if r:
                matched_docs[r[0]] = max(matched_docs.get(r[0], 0.0), score)
    for did, title, ftype, n in rows:
        data = {"id": f"d{did}", "label": title, "file_type": ftype,
                "size": max(n, 1), "color": _COLORS.get(ftype, "#888")}
        if did in matched_docs:
            data["matched"] = True
            data["match_score"] = matched_docs[did]
        nodes.append({"data": data})
    return nodes


def _edges(conn):
    rows = conn.execute(
        "SELECT e.src_chunk_id, e.dst_chunk_id, e.score, cs.document_id, cd.document_id "
        "FROM similarity_edges e "
        "JOIN chunks cs ON cs.id=e.src_chunk_id JOIN chunks cd ON cd.id=e.dst_chunk_id").fetchall()
    scores = [r[2] for r in rows] or [0, 1]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    edges = []
    for src, dst, score, sdoc, ddoc in rows:
        if sdoc == ddoc:
            continue
        width = 1 + 5 * (score - lo) / span      # rescale within observed range
        edges.append({"data": {"id": f"e{src}_{dst}", "source": f"d{sdoc}", "target": f"d{ddoc}",
                               "source_doc": sdoc, "target_doc": ddoc,
                               "weight": round(width, 2), "score": round(score, 3)}})
    return edges


def to_cytoscape(conn, matched=None) -> dict:
    return {"nodes": _doc_nodes(conn, matched), "edges": _edges(conn)}


def to_graphml(conn) -> str:
    g = to_cytoscape(conn)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"><graph edgedefault="undirected">']
    for n in g["nodes"]:
        out.append(f'<node id="{n["data"]["id"]}"><data key="label">'
                   f'{sx.escape(n["data"]["label"])}</data></node>')
    for e in g["edges"]:
        out.append(f'<edge source="{e["data"]["source"]}" target="{e["data"]["target"]}"/>')
    out.append("</graph></graphml>")
    return "\n".join(out)
```

- [ ] **Step 5: Write `app/api/graph.py`**
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Response
from app.graph.export import to_cytoscape, to_graphml
from app.search.service import run_search
from app.models import SearchFilter
from app.api.deps import get_state

router = APIRouter()


@router.get("/graph")
def graph(q: str | None = None, state=Depends(get_state)):
    matched = None
    if q:
        hits = run_search(state.conn, state.embedder, state.vector_index, state.fts_index,
                          query=q, mode="hybrid", flt=SearchFilter(), limit=100, offset=0)
        matched = {h.chunk_id: h.score for h in hits}
    return to_cytoscape(state.conn, matched)


@router.get("/graph/export")
def graph_export(state=Depends(get_state)):
    return Response(to_graphml(state.conn), media_type="application/graphml+xml")
```

- [ ] **Step 6: Wire it in.** In `app/main.py` add `from app.api import graph` and `app.include_router(graph.router)`. In `app/ingest/pipeline.py`, after `db.set_status(..., Status.READY, ...)` add:
```python
            from app.graph.edges import compute_edges_for_document
            compute_edges_for_document(self.conn, self.vector_index, document_id)
```

- [ ] **Step 7: Run** `.venv/bin/pytest tests/test_graph.py -q` → PASS. Then `make test` (full suite) → PASS.
- [ ] **Step 8: Commit** `git commit -am "feat: similarity graph (incremental cross-doc edges), cytoscape/graphml export, graph API"`

---

## Task 17: Eval harness — recall@10 + MRR

**Files:**
- Create: `tests/eval/__init__.py`, `tests/eval/queries.jsonl`, `tests/eval/metrics.py`, `tests/eval/run.py`, `tests/eval/test_metrics.py`

**Interfaces:**
- Produces: `recall_at_k(ranked_ids, relevant_ids, k) -> float`, `mrr(ranked_ids, relevant_ids) -> float`; `make eval` prints per-mode metrics over a fixture corpus using the real embedder.

- [ ] **Step 1: Write `tests/eval/queries.jsonl`** (seed; grow over time)
```
{"q": "refund for a late payment", "relevant_titles": ["hello"]}
{"q": "quarterly revenue", "relevant_titles": ["Memo"]}
{"q": "invoice markdown", "relevant_titles": ["notes"]}
```

- [ ] **Step 2: Write the failing metrics test**

`tests/eval/test_metrics.py`:
```python
from tests.eval.metrics import recall_at_k, mrr


def test_recall_at_k():
    assert recall_at_k([1, 2, 3], {2}, 10) == 1.0
    assert recall_at_k([1, 2, 3], {9}, 10) == 0.0
    assert recall_at_k([1, 2, 3, 4], {3, 9}, 2) == 0.0
    assert recall_at_k([3, 1], {3, 9}, 2) == 0.5


def test_mrr():
    assert mrr([1, 2, 3], {2}) == 0.5
    assert mrr([1, 2, 3], {9}) == 0.0
```

- [ ] **Step 3: Run it** → FAIL.

- [ ] **Step 4: Write `tests/eval/metrics.py`**
```python
from __future__ import annotations


def recall_at_k(ranked_ids, relevant_ids, k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top = ranked_ids[:k]
    return len(set(top) & relevant) / len(relevant)


def mrr(ranked_ids, relevant_ids) -> float:
    relevant = set(relevant_ids)
    for i, cid in enumerate(ranked_ids, 1):
        if cid in relevant:
            return 1.0 / i
    return 0.0
```

- [ ] **Step 5: Write `tests/eval/run.py`** (real-model A/B; run via `make eval`)
```python
"""Ingest the fixture corpus with the REAL embedder and print recall@10 + MRR per mode."""
from __future__ import annotations
import json, tempfile, time
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from tests.eval.metrics import recall_at_k, mrr

CORPUS = [("hello", Path("tests/fixtures/hello.txt").read_text()),
          ("Memo", "quarterly revenue was strong this period"),
          ("notes", Path("tests/fixtures/notes.md").read_text())]


def main():
    with tempfile.TemporaryDirectory() as d:
        client = TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": d})))
        title_to_doc = {}
        for title, text in CORPUS:
            r = client.post("/documents/text", json={"title": title, "text": text})
            title_to_doc[title] = r.json()["id"]
        time.sleep(1)
        queries = [json.loads(l) for l in Path("tests/eval/queries.jsonl").read_text().splitlines() if l.strip()]
        for mode in ("keyword", "semantic", "hybrid"):
            recs, mrrs = [], []
            for item in queries:
                res = client.get("/search", params={"q": item["q"], "mode": mode, "limit": 10}).json()
                ranked = [h["document_id"] for h in res["results"]]
                rel = {title_to_doc[t] for t in item["relevant_titles"] if t in title_to_doc}
                recs.append(recall_at_k(ranked, rel, 10)); mrrs.append(mrr(ranked, rel))
            print(f"{mode:9s}  recall@10={sum(recs)/len(recs):.3f}  MRR={sum(mrrs)/len(mrrs):.3f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run** `.venv/bin/pytest tests/eval/test_metrics.py -q` → PASS; then `make eval` prints three metric lines.
- [ ] **Step 7: Commit** `git commit -am "feat: eval harness (recall@10 + MRR per mode) with seed gold set"`

---

## Task 18: Persistence adapter — SnapshotBackend, VACUUM INTO, restore-on-boot

**Files:**
- Create: `app/persistence/__init__.py`, `app/persistence/backends.py`, `app/persistence/snapshot.py`
- Modify: `app/main.py` (restore on boot, snapshot on shutdown/timer), `app/ingest/pipeline.py` (snapshot after ready; upload original)
- Test: `tests/test_persistence.py`

**Interfaces:**
- Produces:
  - `SnapshotBackend` protocol: `put(key, path)`, `get(key, dest) -> bool`, `exists(key) -> bool`.
  - `LocalSnapshotBackend(dir)`, `S3SnapshotBackend(settings)`, `NoneBackend`.
  - `make_backend(settings) -> SnapshotBackend`.
  - `snapshot_db(conn, backend, db_path)` (VACUUM INTO temp → put), `restore_on_boot(backend, db_path) -> bool`.

- [ ] **Step 1: Write the failing test**
```python
from pathlib import Path
from app import db
from app.persistence.backends import LocalSnapshotBackend
from app.persistence.snapshot import snapshot_db, restore_on_boot


def test_local_snapshot_and_restore(tmp_path):
    store = tmp_path / "store"; store.mkdir()
    dbp = tmp_path / "easynotes.db"
    conn = db.connect(str(dbp)); db.init_schema(conn)
    conn.execute("INSERT INTO documents(id,filename,title,file_type,size,status,content_hash,uploaded_at)"
                 " VALUES (1,'a','a','txt',1,'ready','h','2026')"); conn.commit()
    backend = LocalSnapshotBackend(str(store))
    snapshot_db(conn, backend, str(dbp))
    conn.close(); dbp.unlink()                      # simulate wiped ephemeral disk

    assert restore_on_boot(backend, str(dbp)) is True
    conn2 = db.connect(str(dbp)); db.init_schema(conn2)
    assert conn2.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_restore_returns_false_when_no_snapshot(tmp_path):
    backend = LocalSnapshotBackend(str(tmp_path / "empty"))
    assert restore_on_boot(backend, str(tmp_path / "x.db")) is False
```

- [ ] **Step 2: Run it** → FAIL.

- [ ] **Step 3: Write `app/persistence/backends.py`**
```python
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Protocol

SNAPSHOT_KEY = "easynotes.db"


class SnapshotBackend(Protocol):
    def put(self, key: str, path: str) -> None: ...
    def get(self, key: str, dest: str) -> bool: ...
    def exists(self, key: str) -> bool: ...


class NoneBackend:
    def put(self, key, path): pass
    def get(self, key, dest): return False
    def exists(self, key): return False


class LocalSnapshotBackend:
    def __init__(self, directory: str):
        self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True)

    def put(self, key, path): shutil.copy2(path, self.dir / key)
    def get(self, key, dest):
        src = self.dir / key
        if not src.exists():
            return False
        shutil.copy2(src, dest); return True
    def exists(self, key): return (self.dir / key).exists()


class S3SnapshotBackend:
    def __init__(self, settings):
        import boto3
        self.bucket = settings.snapshot_bucket
        self.s3 = boto3.client("s3", endpoint_url=settings.snapshot_endpoint,
                               aws_access_key_id=settings.snapshot_access_key,
                               aws_secret_access_key=settings.snapshot_secret_key)

    def put(self, key, path): self.s3.upload_file(path, self.bucket, key)
    def get(self, key, dest):
        try:
            self.s3.download_file(self.bucket, key, dest); return True
        except Exception:
            return False
    def exists(self, key):
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key); return True
        except Exception:
            return False


def make_backend(settings) -> SnapshotBackend:
    kind = settings.snapshot_backend
    if kind == "s3":
        return S3SnapshotBackend(settings)
    if kind == "local":
        return LocalSnapshotBackend(str(Path(settings.data_dir) / "_snapshots"))
    return NoneBackend()
```

- [ ] **Step 4: Write `app/persistence/snapshot.py`**
```python
from __future__ import annotations
import tempfile, os
from pathlib import Path
from app.persistence.backends import SNAPSHOT_KEY

ORIGINALS_PREFIX = "originals/"


def snapshot_db(conn, backend, db_path: str) -> None:
    """Consistent snapshot via VACUUM INTO (safe under concurrent writes), then upload."""
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, "snap.db")
        conn.execute("VACUUM INTO ?", (tmp,))
        backend.put(SNAPSHOT_KEY, tmp)


def restore_on_boot(backend, db_path: str) -> bool:
    """If the local DB is missing and a snapshot exists, install it. Returns True if restored."""
    if Path(db_path).exists():
        return False
    if not backend.exists(SNAPSHOT_KEY):
        return False
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return backend.get(SNAPSHOT_KEY, db_path)


def upload_original(backend, path: str, key_name: str) -> None:
    backend.put(ORIGINALS_PREFIX + key_name, path)
```

- [ ] **Step 5: Wire into `app/main.py`** — before `db.connect`, restore; expose backend; snapshot on shutdown:
```python
    from app.persistence.backends import make_backend
    from app.persistence.snapshot import restore_on_boot, snapshot_db
    backend = make_backend(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = str(data_dir / "easynotes.db")
        restore_on_boot(backend, db_path)          # ephemeral-tier durability
        conn = db.connect(db_path)
        db.init_schema(conn); db.mark_interrupted(conn)
        # ... existing wiring ...
        app.state.backend = backend
        yield
        try:
            snapshot_db(conn, backend, db_path)     # final snapshot on shutdown
        finally:
            conn.close()
```
And in `app/ingest/pipeline.py`, after edges are computed, snapshot (write-event trigger) and upload the original:
```python
            from app.persistence.snapshot import snapshot_db
            if getattr(self, "backend", None):
                snapshot_db(self.conn, self.backend, self.db_path)
```
Add `backend`/`db_path` params to `IngestionPipeline.__init__` (default `None`) and pass them from `create_app`.

- [ ] **Step 6: Run** `.venv/bin/pytest tests/test_persistence.py -q` → PASS; `make test` full → PASS.
- [ ] **Step 7: Commit** `git commit -am "feat: snapshot/restore persistence (Local/S3/None), VACUUM INTO, restore-on-boot"`

---

## Task 19: Web UI — upload/paste, search, similarity graph

**Files:**
- Create: `static/index.html`, `static/app.js`, `static/styles.css`, `static/cytoscape.min.js` (vendored)
- Modify: `app/main.py` (mount static at `/`)
- Manual QA (no automated test in v1).

- [ ] **Step 1: Vendor Cytoscape** — download `cytoscape.min.js` into `static/` (pinned version; committed so the image is self-contained, no CDN).

- [ ] **Step 2: Mount static in `app/main.py`**
```python
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
```
(Mount **after** all API routers so `/documents`, `/search`, `/graph` win.)

- [ ] **Step 3: Write `static/index.html`** — three tabs (Upload/Paste, Search, Graph), a drag-drop zone, a recent-uploads list that polls `/documents`, a search box with a mode toggle + filters, and a `<div id="cy">` for the graph. (Full markup ~120 lines; keep it dependency-free vanilla JS.)

- [ ] **Step 4: Write `static/app.js`** — `fetch` calls to `POST /documents`, `POST /documents/text`, poll `GET /documents/{id}` for status, `GET /search` renders snippet cards with the matched term highlighted, `GET /graph`/`GET /graph?q=` renders Cytoscape with node size = `data.size`, color = `data.color`, edge width = `data.weight`, and dims non-`matched` nodes when a query is active.

- [ ] **Step 5: Write `static/styles.css`** — minimal responsive layout; tables/graph scroll inside their own containers.

- [ ] **Step 6: Manual QA checklist** (run `make run`, open http://localhost:8000):
  - [ ] Drag-drop a PDF → shows `processing` → `ready`; a bad file shows the failure reason.
  - [ ] Paste text with a title → becomes searchable.
  - [ ] Search in each mode returns source-grouped snippet cards with highlighting.
  - [ ] Graph shows document nodes colored by type; a query dims non-matches and badges matches.
  - [ ] `GET /graph/export` downloads GraphML.

- [ ] **Step 7: Commit** `git commit -am "feat: static web UI (upload/paste, search, similarity graph)"`

---

## Task 20: `501` answer slot + finalize README/DECISIONS

**Files:**
- Create: `app/api/answer.py`
- Modify: `app/main.py` (register answer router), `README.md`, `DECISIONS.md`
- Test: `tests/test_answer.py`

**Interfaces:**
- Produces: `POST /answer` → `501` with an enable-instructions body; depends on the retrieval service (structure the future LLM module plugs into).

- [ ] **Step 1: Write the failing test**
```python
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings
from app.search.embeddings import FakeEmbedder


def test_answer_returns_501_with_instructions(tmp_path):
    c = TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": str(tmp_path)}),
                              embedder=FakeEmbedder(dim=16)))
    r = c.post("/answer", json={"q": "anything"})
    assert r.status_code == 501
    assert "LLM" in r.json()["detail"]
```

- [ ] **Step 2: Run it** → FAIL.

- [ ] **Step 3: Write `app/api/answer.py`**
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.deps import get_state

router = APIRouter()


class AnswerReq(BaseModel):
    q: str
    mode: str = "hybrid"


@router.post("/answer")
def answer(body: AnswerReq, state=Depends(get_state)):
    # The retrieval half is ready and shared with /search; only generation is absent.
    raise HTTPException(
        status_code=501,
        detail=("Answer synthesis is not enabled. EasyNotes is LLM-free by default. "
                "To enable: add a synthesizer module that calls run_search() (already the "
                "shared retrieval function) and set an LLM API key. See DECISIONS.md."))
```

- [ ] **Step 4: Wire** `from app.api import answer` + `app.include_router(answer.router)` in `app/main.py` (before the static mount).
- [ ] **Step 5: Run** `.venv/bin/pytest tests/test_answer.py -q` → PASS; `make test` full → PASS.

- [ ] **Step 6: Finalize `README.md`** — expand to: what it is, quick start (`setup-mac.sh`, `make run`, `make docker-run`), the full command table (`run`/`test`/`eval`/`docker-build`/`docker-run`), API reference (each endpoint with a `curl` example), the architecture section (the ingestion→index→search diagram from the spec, the three search modes, the graph, the R2 snapshot/restore durability model), deployment to Render free + R2 (env vars, single-writer note), and a "how it's LLM-free / how to add an LLM" section pointing at the `501` slot.

- [ ] **Step 7: Append a DECISIONS.md entry** for anything discovered during the build (e.g. sqlite-vec availability on the dev machine, final chunk-size after eval).

- [ ] **Step 8: Commit** `git commit -am "feat: 501 answer slot; finalize README and DECISIONS"`

---

## Self-review (completed by plan author)

**Spec coverage:** every §-section maps to a task — ingestion/parsers → 8,11–15; chunker → 7; storage/schema → 3; search modes + sanitizer + RRF → 6,9; embedder split → 4; vector fallback + contract → 5; graph → 16; persistence → 18; error handling/interrupted recovery → 3,9; testing/eval → all + 17; Docker/offline → 10; UI → 19; 501 slot → 20; the 4 protocols → 4,5,8,18. Deferred items (OCR, reranker, small-to-big, CJK, Postgres/Approach B, auth) remain out of scope per spec §13.

**User's seven deliverables:** (1) detailed plan with per-task tests ✓ every task is TDD; (2) `make run` ✓ Task 1; (3) `make docker-build` ✓ Task 1/10; (4) build+deploy locally `make docker-run` ✓ Task 1/10; (5) `setup-mac.md` + `scripts/setup-mac.sh` installing python/docker/deps ✓ Task 1; (6) `DECISIONS.md` ✓ Task 1 (seeded) + Task 20 (finalized); (7) `README.md` usage + architecture ✓ Task 1 (skeleton) + Task 20 (full).

**Type consistency:** `ScoredChunk(chunk_id, score)`, `SearchHit` fields, `Embedder.embed_query/embed_passages`, `VectorIndex.add/search/delete_document`, `run_search(...)` signature, and `IngestionPipeline.ingest(document_id)` are used identically across tasks 4–20.







