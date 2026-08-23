# EasyNotes

**Dump any file, find it in plain English.**

EasyNotes ingests unstructured documents — PDF, DOCX, PPTX, XLSX, CSV, Markdown,
plain text, or pasted notes — and makes them searchable by keyword, natural
language, or a hybrid of both, with an interactive similarity graph of your
corpus. It runs as a single container, is fully self-hosted, uses **no LLM**, and
costs **nothing per query**.

> Despite the name, EasyNotes handles far more than notes — spreadsheets, slide
> decks, and PDFs all go in the same box.

## Quick start (macOS)

```bash
bash scripts/setup-mac.sh   # installs Homebrew, Python 3.12, Docker, and deps
make run                    # http://localhost:8000
```

Prefer the container?

```bash
make docker-run             # builds the image AND runs it at http://localhost:8000
```

| Command | What it does |
|---|---|
| `make run` | Run locally with hot reload |
| `make test` | Run the full test suite |
| `make eval` | Print retrieval quality (recall@10, MRR) per mode |
| `make docker-build` | Build the Docker image only |
| `make docker-run` | Build the image **and** run the container locally |
| `make docker-test` | Prove the container boots + searches with **no network** |
| `make docker-stop` | Stop the local container |

## How it works (architecture)

```
Upload (file or pasted text)
   → Validate (size, MIME sniff, dedup, zip-bomb limits)
   → Parse   (one module per format → text blocks + metadata)
   → Chunk   (~300 model-tokens, contextual headers; tables by row-group)
   → Embed   (fastembed bge-small-en-v1.5, 384-dim, ONNX — no LLM)
   → Index   (SQLite FTS5 for keyword  +  sqlite-vec for semantic)
   → Search  (keyword | semantic | hybrid via Reciprocal Rank Fusion)
   → Graph   (cross-document similarity edges, rendered with Cytoscape.js)
```

**One process, one file.** FastAPI serves the API and UI; SQLite is the only
datastore (no database server to run, **no credentials to procure** — the
"database" is just `data/easynotes.db`). Ingestion runs in a background task.

**Search modes**
- **keyword** — FTS5/BM25 with a query sanitizer; exact terms, phrases, `AND/OR`,
  plus filters (file type, document). Your "defined queries."
- **semantic** — embeds your question and finds passages by meaning. Natural
  language.
- **hybrid** (default) — fuses both with RRF (`k=60`), no tuning.

**The similarity graph** shows each document as a node (sized by chunk count,
colored by type) with edges between semantically similar documents. Typing a
query lights up the matching nodes.

**Durability without a server.** SQLite is embedded, so on an ephemeral host the
disk is wiped on restart. EasyNotes snapshots the DB (`VACUUM INTO`) to
S3-compatible object storage after every ingest and restores it on boot — giving
durable storage at **$0** on a free tier. Set `SNAPSHOT_BACKEND=none` (default)
for pure local use.

## Key components

| Path | Responsibility |
|---|---|
| `app/main.py` | Composition root (`create_app`) + startup self-check |
| `app/ingest/parsers/` | One parser per format, behind a registry |
| `app/ingest/chunker.py` | Token-budgeted chunking + contextual headers |
| `app/ingest/pipeline.py` | parse → chunk → embed → index orchestration |
| `app/search/embeddings.py` | fastembed embedder (query/passage split) |
| `app/search/vectors.py` | sqlite-vec index + numpy fallback (one interface) |
| `app/search/fts.py` | FTS5 keyword index + query sanitizer |
| `app/search/service.py` | Shared retrieval used by search, graph, and the answer slot |
| `app/graph/` | Similarity-edge computation + Cytoscape/GraphML export |
| `app/persistence/` | Snapshot/restore backends (local / S3 / none) |

## API

| Method & path | Purpose |
|---|---|
| `POST /documents` | Upload a file (multipart) |
| `POST /documents/text` | Ingest pasted text (`{title, text}`) |
| `GET /documents` / `GET /documents/{id}` | List / status |
| `DELETE /documents/{id}` | Remove a document (and all its index rows) |
| `GET /search?q=&mode=&type=&doc_id=&limit=&offset=` | Search |
| `GET /graph` / `GET /graph?q=` | Similarity graph (with query highlighting) |
| `GET /graph/export` | GraphML export (Gephi-compatible) |
| `POST /answer` | **501** — the LLM slot (see below) |
| `GET /healthz` | Health check |

Example:

```bash
curl -F "file=@report.pdf" localhost:8000/documents
curl "localhost:8000/search?q=refund%20policy&mode=hybrid"
```

## Configuration (env vars)

`DATA_DIR`, `MAX_UPLOAD_MB`, `EMBED_MODEL`, `EMBED_CACHE_DIR`, `EMBED_MODEL_PATH`,
`EMBED_THREADS` (default 1), `EMBED_BATCH_SIZE`, `EDGE_SIMILARITY_FLOOR`, and the
snapshot block: `SNAPSHOT_BACKEND` (`none`|`local`|`s3`), `SNAPSHOT_ENDPOINT`,
`SNAPSHOT_BUCKET`, `SNAPSHOT_ACCESS_KEY`, `SNAPSHOT_SECRET_KEY`,
`SNAPSHOT_INTERVAL_S`.

## Deploying to a free tier (Render + Cloudflare R2)

Render's free web service has an ephemeral disk, so durability comes from R2
snapshots (10 GB free, free egress):

1. Create an R2 bucket and an API token (access key + secret).
2. Deploy the Docker image to Render (free web service).
3. Set: `SNAPSHOT_BACKEND=s3`, `SNAPSHOT_ENDPOINT=<your-r2-endpoint>`,
   `SNAPSHOT_BUCKET=<bucket>`, `SNAPSHOT_ACCESS_KEY`, `SNAPSHOT_SECRET_KEY`.

> **Single writer only.** This design assumes exactly one instance — never scale
> horizontally, or snapshots will race.

The same image also runs anywhere with a real disk (Render Starter + disk, an
Oracle Always-Free VM, or your own machine) with `SNAPSHOT_BACKEND=none`.

## Why LLM-free? (and how to add an LLM later)

EasyNotes is the **retrieval** half of a RAG system with no generation stage —
that keeps it free, private, and self-contained. `POST /answer` already exists as
a `501` stub wired to the shared retrieval service, so enabling answer synthesis
later is one module plus an API key, with no change to search. See `DECISIONS.md`.

## Development

TDD throughout (`make test`). The steel thread (upload → search) is proven
end-to-end inside the offline Docker image (`make docker-test`). Retrieval quality
is measured with `make eval`.
