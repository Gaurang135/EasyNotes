# Corpora — Design Spec

**Date:** 2026-08-23
**Status:** Approved (brainstorming complete)
**Type:** Learning/portfolio project

## 1. Purpose

A single-container Python service that ingests unstructured documents
(PDF, DOCX, PPTX, XLSX, CSV, MD, TXT, pasted text) and makes them searchable
via both defined queries (keyword, boolean, filters) and natural-language
queries (semantic search) — with a web UI that includes an interactive
similarity graph of the corpus.

**Explicitly LLM-free.** The system is the retrieval half of a RAG
architecture with no generation stage: zero per-query cost, fully
self-hosted, deployable to free hosting tiers. A clearly marked extension
slot exists for adding LLM answer-synthesis later.

### Goals
- Learn every layer of a document ingestion + retrieval system by building
  it (no LlamaIndex/LangChain).
- Runnable locally with `docker run`; deployable unchanged to a free tier
  (HF Spaces, Oracle free VM, Render) later.
- Zero external services, zero per-query cost.

### Non-goals (v1)
- No LLM / answer generation (extension slot only).
- No auth / multi-user (single-user; stated decision, not oversight).
- No OCR for scanned PDFs (listed extension).
- No entity-level knowledge graph (similarity graph only; listed extension).
- No horizontal scaling; corpus scale target is hundreds to a few thousand
  documents.

## 2. Architecture

One FastAPI container. SQLite is the only store (single file).

```
Upload (file or pasted text)
   → Parser (per-format extractor → text blocks + metadata)
   → Chunker (~300-token chunks, overlap; tables → row-group chunks)
   → Indexer: SQLite FTS5 (BM25)  +  sqlite-vec (fastembed vectors)
   → Query API: keyword | semantic | hybrid → ranked snippets + sources
   → UI: search + Cytoscape.js similarity graph with query highlighting
```

### Key technology decisions
| Concern | Choice | Rationale |
|---|---|---|
| API | FastAPI | Standard, async, TestClient for tests |
| Storage | SQLite (one file) | No DB service to host; free-tier friendly |
| Keyword search | FTS5 virtual table, BM25 | Built into sqlite3; mature |
| Embeddings | fastembed, `bge-small-en-v1.5` (384-dim) | ONNX, no torch, ~200MB RAM — fits 512MB free instances |
| Vector search | sqlite-vec | Keeps vectors in the same DB file |
| Vector fallback | numpy brute-force cosine behind same interface | At ≤ tens of thousands of chunks this is milliseconds; removes sqlite-vec as a hard dependency |
| Hybrid ranking | Reciprocal Rank Fusion | Simple, no weight tuning |
| Ingestion execution | FastAPI BackgroundTasks in thread executor | Single process; ONNX releases the GIL |
| UI | Static HTML/JS + Cytoscape.js, served by FastAPI | No build step; tiny image |
| Config | Env vars only (`DATA_DIR`, `MAX_UPLOAD_MB`, `EMBED_MODEL`) | Same image everywhere |

The embedding model is baked into the Docker image so first boot needs no
internet.

## 3. Ingestion

`POST /documents` (multipart) or `POST /documents/text` (pasted text +
title) → file saved under `DATA_DIR` → background task runs
parse → chunk → embed → index, updating document status:
`pending → processing → ready | failed` (+ human-readable error). UI polls
`GET /documents/{id}`.

- **Parsers:** one module per format behind a common interface
  `parse(path) -> ParsedDoc{text_blocks, metadata}`. Libraries: pypdf,
  python-docx, python-pptx, openpyxl, stdlib csv; md/txt read directly.
  Adding a format = adding one module.
- **Chunker:** ~300-token chunks with overlap; each chunk records a
  location hint (page / slide / sheet + row range). Spreadsheets chunk by
  row groups with the header row prepended to each chunk.
- **Validation:** extension + MIME sniff; size cap (default 25MB);
  duplicate detection via content hash (re-upload returns existing doc).
- **Partial success allowed:** unreadable pages are skipped and recorded
  as warnings; only total extraction failure marks the document `failed`.
- Original files are retained under `DATA_DIR` to allow future re-indexing
  without re-upload.
- After each ingestion, cross-document top-k similarity edges are
  (re)computed for the graph.

## 4. Storage schema (SQLite, one file)

- `documents` — id, filename, title, file_type, size, status, error,
  warnings, content_hash, uploaded_at
- `chunks` — id, document_id, seq, text, location hint
- `chunks_fts` — FTS5 virtual table over chunk text
- `chunk_vectors` — sqlite-vec table, 384-dim embeddings
- `similarity_edges` — precomputed top-k nearest-neighbor chunk pairs
  across different documents (powers the graph; refreshed on ingest)

Migrations run automatically at startup.

## 5. Search

`GET /search?q=...&mode=hybrid|keyword|semantic&type=pdf&doc_id=...&limit=20&offset=0`

- **keyword** — FTS5 BM25; quoted phrases, AND/OR. Plus structured
  filters: file type, date range, specific document. ("Defined queries.")
- **semantic** — embed query via fastembed, cosine top-k.
- **hybrid (default)** — both, merged with RRF. ("Natural language.")

Results are chunk-level: highlighted snippet, source document, location
hint, score; paginated; grouped by document in the UI.

**LLM extension slot:** `POST /answer` exists and returns
`501 Not Implemented` with instructions. It would call the same retrieval
function `/search` uses; enabling it later = one module + an API key.

## 6. API surface

- `POST /documents` · `POST /documents/text` · `GET /documents` ·
  `GET /documents/{id}` · `DELETE /documents/{id}`
- `GET /search` (as above)
- `GET /graph` — Cytoscape-ready JSON: document nodes (sized by chunk
  count, colored by file type) + chunk nodes (collapsed by default) +
  similarity edges. `GET /graph?q=...` additionally marks matching nodes
  with scores.
- `GET /graph/export` — portable GraphML/JSON export (Gephi-compatible).
- `POST /answer` — 501 stub (LLM slot).
- `GET /healthz`.
- CORS configurable for potential split hosting later.

## 7. UI (static, no build step)

Single-page app, three views + ever-present upload:

1. **Input / landing** — tabs: *Upload files* (drag-drop or browse,
   multi-file, supported-format hints) and *Paste text* (title + textarea).
   Recent-uploads list with live status (ready / processing / failed with
   reason), polling the status endpoint.
2. **Search** — query box, mode toggle (hybrid/keyword/semantic), filters;
   source-grouped snippet cards with term highlighting; click through to a
   document detail pane listing all its chunks.
3. **Graph** — Cytoscape.js force-directed view. Document nodes colored by
   file type; chunk nodes expand on click; edge thickness = similarity.
   Click node → side panel text preview. Typing a query dims non-matching
   nodes and highlights matches with score badges (search-on-graph).

Graph performance guardrails: document-level nodes by default, chunk
expansion on demand, edges capped at top-k.

## 8. Error handling

- Ingestion failures never crash the service; they mark the document
  `failed` with a readable reason (encrypted PDF, corrupt file, empty
  text, unsupported content).
- Scanned/image-only PDFs fail with an explicit "no extractable text
  (needs OCR)" reason.
- Invalid FTS5 query syntax falls back to a plain-term query; searches
  never 500 on user input.
- Startup self-check: embedding model loads (fail fast), FTS5 available,
  migrations applied.

## 9. Testing (TDD)

- **Parser unit tests** with tiny committed fixtures (2-page PDF, 3-slide
  PPTX, small DOCX/XLSX/CSV/MD) — highest-value tests; parsers are the
  flakiest layer.
- **Chunker tests:** boundaries, overlap, table row-grouping, location
  hints.
- **Search integration tests:** in-memory SQLite; ingest fixtures; assert
  known queries return expected chunks per mode. Semantic tests assert
  rank presence, not exact scores.
- **API tests** (FastAPI TestClient): upload → poll → search → graph;
  failure paths (bad file, oversized, duplicate, bad query).
- UI exercised manually in v1.

## 10. Implementation strategy — steel thread first

**Phase 1 is the POC, kept as real code:** minimal end-to-end slice —
upload one `.txt` → chunk → embed → index → hybrid search returns it —
running inside the target slim Docker image, with tests. This proves the
one integration that argument can't: fastembed + sqlite-vec + FTS5
together in one image. If sqlite-vec fights us, the numpy fallback swaps
in behind the vector-store interface.

Subsequent phases add parsers (one at a time, fixture-tested), the
similarity graph, and the UI — each independently testable.

## 11. Project layout

```
corpora/
├── app/
│   ├── main.py            # FastAPI wiring
│   ├── api/               # routes: documents, search, graph, answer(501)
│   ├── ingest/            # parsers/ (one per format), chunker, pipeline
│   ├── search/            # fts, vectors (+ fallback), hybrid RRF, embeddings
│   ├── graph/             # edge computation, export
│   └── db.py              # SQLite schema + migrations
├── static/                # index.html, app.js, styles.css, cytoscape
├── tests/  (+ fixtures/)
├── Dockerfile             # single stage, slim, model baked in
├── docker-compose.yml     # local run with data volume
└── README.md
```

## 12. Future extensions (explicitly out of v1)

- LLM answer synthesis via `POST /answer` (free tiers: Groq / Gemini).
- OCR for scanned PDFs (pytesseract).
- Entity-level knowledge graph (spaCy NER) alongside the similarity graph.
- Queue/worker + Postgres/pgvector migration (Approach B) as a phase-2
  architecture exercise.
- Auth for multi-user deployment.
- Persistent-storage adapter for ephemeral hosts (HF Spaces + HF Dataset).
