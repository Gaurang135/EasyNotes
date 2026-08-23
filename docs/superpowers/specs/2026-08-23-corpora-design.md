# Corpora — Design Spec

**Date:** 2026-08-23 (LLD section added 2026-08-24)
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
internet. The SQLite database file lives under `DATA_DIR` alongside the
original documents, so persistence adapters (see §13) have a single
directory to preserve.

## 3. Ingestion

`POST /documents` (multipart) or `POST /documents/text` (pasted text +
title) → file saved under `DATA_DIR` → background task runs
parse → chunk → embed → index, updating document status:
`pending → processing → ready | failed` (+ human-readable error). UI polls
`GET /documents/{id}`.

- **Parsers:** one module per format behind a common `Parser` protocol
  (see §8). Libraries: pypdf, python-docx, python-pptx, openpyxl, stdlib
  csv; md/txt read directly. Adding a format = adding one module plus one
  registry entry.
- **Chunker:** ~300-token chunks with overlap; each chunk records a
  location hint (page / slide / sheet + row range). Spreadsheets chunk by
  row groups with the header row prepended to each chunk. One concrete
  chunker; prose vs table handling is a branch on the text block's `kind`,
  not a strategy hierarchy.
- **Validation:** extension + MIME sniff, size cap (default 25MB), and
  content-hash dedup (re-upload returns existing doc) all happen in one
  validation module *before* parser lookup — parsers never validate.
- **Partial success allowed:** unreadable pages are skipped and recorded
  in `ParsedDoc.warnings`; parsers raise only on total extraction failure,
  using a typed error taxonomy (§8).
- Original files are retained under `DATA_DIR` to allow re-indexing
  without re-upload.
- **Re-ingest path (v1 requirement):** an idempotent internal re-ingest
  operation purges a document's chunks, FTS rows, vectors, and similarity
  edges in one transaction, then re-runs the pipeline from the retained
  original. This is what future OCR and embedding-model changes hook into.
- After each ingestion, cross-document top-k similarity edges are computed
  **incrementally** — the new document's chunks against the existing
  corpus (pruning displaced edges) — never a full O(N²) rebuild. A full
  rebuild exists only as an explicit admin re-index path.

## 4. Storage schema (SQLite, one file)

- `documents` — id, filename, title, file_type, size, status, error,
  warnings, content_hash, uploaded_at
- `chunks` — id, document_id, seq, text, location hint
- `chunks_fts` — FTS5 virtual table over chunk text
- `chunk_vectors` — sqlite-vec table, 384-dim embeddings
- `similarity_edges` — precomputed top-k nearest-neighbor chunk pairs
  across different documents (powers the graph; refreshed on ingest)
- `meta` — embedding model name and dimension recorded at first index;
  checked by the startup self-check (a mismatch with `EMBED_MODEL` means
  stored vectors are invalid → refuse to start with a clear message
  pointing at the re-index path)

Migrations run automatically at startup. **Deletion integrity:** FTS5 and
sqlite-vec virtual tables ignore foreign-key cascades, so
`DELETE /documents/{id}` removes rows from `chunks`, `chunks_fts`,
`chunk_vectors`, and `similarity_edges` (both directions) in a single
transaction, plus the original file — centralized in one function and
covered by an API test.

**Connection semantics (pinned in Phase 1):** WAL mode, `busy_timeout`
set, and a per-thread connection policy — a background ingestion thread
writes while request threads read, and the steel thread must not discover
"database is locked" by accident.

## 5. Search

`GET /search?q=...&mode=hybrid|keyword|semantic&type=pdf&doc_id=...&limit=20&offset=0`

- **keyword** — FTS5 BM25; quoted phrases, AND/OR. Plus structured
  filters: file type, date range, specific document. ("Defined queries.")
- **semantic** — embed query via fastembed, cosine top-k, filters applied
  post-retrieval with over-fetch (no filter pushdown into the vector
  index; at our scale this is milliseconds).
- **hybrid (default)** — both, merged with RRF. ("Natural language.")

Retrieval is an importable service function — not logic inside the HTTP
handler — because three consumers share it: `GET /search`, `GET /graph?q=`,
and the future `POST /answer`. Hydration and snippeting happen in this
service layer above both indexes; keyword hits use FTS5 `snippet()`,
semantic hits get snippets synthesized from chunk text. **Search results
(`SearchHit`) carry the full chunk text** in addition to the highlighted
snippet — without this, the LLM extension slot's "one module + an API key"
promise would be false (a synthesizer needs context, not snippets). The
HTTP response may omit full text; the internal result type must not.

**LLM extension slot:** `POST /answer` exists and returns
`501 Not Implemented` with instructions. The route already depends on the
retrieval service (one `Depends` line), so its retrieve-then-synthesize
shape is real, tested structure; enabling it later = one synthesizer
module + an API key. No synthesizer interface, provider registry, or
prompt machinery exists in v1.

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

## 8. Low-level design: SOLID & extension seams

Reviewed through three independent lenses (SOLID rigor, YAGNI pragmatism,
evolution/testability) plus an adversarial pass. The governing rule:
**a Protocol exists only where there is a planned second implementation or
a concrete testing need.** Of 11 candidate abstractions, exactly three
survive; everything else is a concrete class or a plain function.

### 8.1 The three Protocols

**`Parser`** — seven v1 implementations, one per format; future OCR.

```python
class Parser(Protocol):
    file_types: ClassVar[frozenset[str]]   # canonical: extension sans dot, e.g. {"pdf"}
    def parse(self, path: Path) -> ParsedDoc: ...

@dataclass(frozen=True)
class ParsedDoc:
    text_blocks: list[TextBlock]   # TextBlock(text, kind: Literal["prose","table"], location: LocationHint)
    metadata: dict[str, str]
    warnings: list[str]            # partial-success channel (skipped pages etc.)
```

Parsers raise a **typed error taxonomy** (`ParseError` base:
`EncryptedFileError`, `CorruptFileError`, `NoExtractableTextError`,
`EmptyDocumentError`). The pipeline maps exception type → the
human-readable reasons of §9; typed errors are load-bearing because the
future OCR parser dispatches on `NoExtractableTextError` — a
string-matched message would make that seam fragile. `ParsedDoc`,
`TextBlock`, `Chunk`, and `SearchHit` are frozen dataclasses in one shared
models module — one contract, not parallel ad-hoc dicts. `TextBlock.kind`
is required: row-group chunking branches on prose vs table.

**`VectorIndex`** — two v1 implementations; the spec-mandated fallback.

```python
class VectorIndex(Protocol):
    def add(self, items: Sequence[tuple[int, list[float]]]) -> None: ...
    def search(self, vector: list[float], k: int) -> list[ScoredChunk]: ...
    def delete_document(self, document_id: int) -> None: ...
    # CONTRACT: score is cosine SIMILARITY, higher-is-better, stable ordering — every impl
```

`SqliteVecIndex` (primary) and `NumpyVectorIndex` (brute-force fallback,
also the default in most tests). Chosen **once at startup** by a ~10-line
factory that probes sqlite-vec loadability; the bound instance is shared
by both retrieval and graph-edge computation. **Score-direction trap
(highest-risk bug in this design):** sqlite-vec natively returns
*distance* (lower = better); the conversion to similarity lives inside
`SqliteVecIndex` and nowhere else. RRF only sees ranks, so an inverted
semantic leg would look plausible while ranking backwards — which is why
a shared **contract-test suite parametrized over both implementations**
(same scoring semantics, ordering, ties, empty-index, delete behavior)
exists from Phase 1. The fallback promise is only real if both are green
on the same behavioral tests the day the lever gets pulled. Future
`PgVectorIndex` joins the same suite. No filter parameter in the port —
semantic filters are post-applied with over-fetch (retrofit later is a
small in-repo diff, not a migration).

**`Embedder`** — one real implementation; the seam exists for tests.

```python
class Embedder(Protocol):
    dim: int
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
```

`FastembedEmbedder` (bge-small-en-v1.5) plus a deterministic
`FakeEmbedder` in tests: the ~200MB ONNX model must never load in unit
tests. The real model is constructed only in the composition root (never
at module import, never lazily in a route) — which is also what makes the
§9 fail-fast startup check possible.

### 8.2 Patterns in use (and their ceilings)

| Pattern | Where | Ceiling — deliberately not more |
|---|---|---|
| Registry (literal dict) | `PARSERS: dict[str, Parser]` in `app/ingest/parsers/__init__.py`; keys = canonical file_type; built explicitly in the composition root | No importlib scanning, no entry_points, no registration decorators — explicit and grep-able |
| Strategy chosen at boot | vector-index factory probes sqlite-vec → binds one instance | One decision, at startup, never per-query |
| Dispatch table | search modes `{"keyword", "semantic", "hybrid"}` → three functions on one concrete search service | Never Strategy classes; no new mode is planned |
| Pure function | `rrf(rank_lists, k=60)` (~10 lines); graph exporters (Cytoscape JSON, GraphML) as two serializers over one neutral node/edge model | No Fuser interface (spec chose RRF *because* it needs no tuning); no GraphExporter Protocol (no call site ever substitutes one exporter for another) |
| Facade | `IngestionPipeline` — one class holding injected deps (`registry, chunker, embedder, fts_index, vector_index, db`), one method `ingest(document_id)`; owns the status machine and the never-crash try/except | Nearly a plain function; the class exists to hold dependencies for tests. No hooks, no Template Method |
| Composition root | `create_app(settings)` + FastAPI lifespan: run migrations, load embedder (fail fast), probe FTS5, probe sqlite-vec, wire everything onto `Depends` providers | Construction *is* the §9 startup self-check. No DI container — ~30 explicit lines. Tests override via `dependency_overrides`, never monkeypatching |

Two disciplines with no pattern name, both load-bearing:

- **Zero FastAPI imports inside `app/ingest/`** (no `UploadFile`,
  `BackgroundTasks`, `Request`). Routes drain the upload to disk and pass
  plain ids to `pipeline.ingest(document_id)`. That call signature *is*
  the queue-worker migration seam — a future Celery/RQ worker imports and
  calls it as-is. One leaked `UploadFile` turns the phase-2 migration
  into a rewrite.
- **Ingestion submission stays on literal FastAPI `BackgroundTasks`** at
  its one call site: Starlette's TestClient executes background tasks
  synchronously, which is what makes API tests deterministic
  (upload → assert `ready`, no polling/sleeps). Drifting to a hand-rolled
  executor forfeits that and would revive a TaskRunner abstraction we
  rejected.

### 8.3 SOLID mapping

- **S** — responsibility at module level: each parser owns one format and
  one library; `chunker.py` only splits and stamps locations; validation
  (MIME/size/dedup) is one module that runs before parser lookup;
  `fts.py` owns FTS5 syntax (including the bad-query fallback — inside
  the index class, so "searches never 500" survives any backend swap);
  `vectors.py` owns the two vector impls; `hybrid.py` owns fusion and
  hydration; `graph/edges.py` computes, exporters only serialize;
  routes translate HTTP and nothing else.
- **O** — every §13 extension lands as *addition*: new format = new
  parser module + registry entry; OCR = wrap the `pdf` registry entry;
  pgvector = third `VectorIndex` impl; LLM answers = one synthesizer
  module filling the 501 slot; new export format = one serializer. The
  only existing file any of these touches is the composition root — by
  design. Everything else (chunker, RRF, schema) is explicitly *closed*:
  modify directly when needs change, don't pre-open.
- **L** — two substitution contracts, both test-enforced: the vector
  contract suite (above), and all parsers honoring partial-success
  (warnings for page-level failures, typed raise only for total failure)
  — verified per format by fixture tests.
- **I** — interfaces sized to their callers: `Parser` is `parse()` only;
  `VectorIndex` is add/search/delete — it is not forced to fake BM25 or
  filters; `Embedder` is `dim` + `embed`. No fat `SearchBackend` or
  `Store` interface bundling FTS + vectors + documents.
- **D** — pipeline, search service, and edge computation import only
  Protocols and shared dataclasses; concretions (pypdf, fastembed,
  sqlite-vec, numpy) are each imported in exactly one leaf module and
  chosen in `create_app`. Inversion stops at the DB: `db.py` depends on
  sqlite3 concretely and proudly — abstracting the thing the project
  exists to teach would be self-defeating.

### 8.4 Rejected abstractions (decisions, not oversights)

Considered and rejected for v1 — each was proposed by at least one review
lens and killed for abstracting over zero planned implementations:

Repository/DAO/ORM layer over SQLite (the Postgres migration is an
explicit phase-2 *rewrite exercise*; raw SQL in narrow modules is the
point) · `TaskRunner` protocol over BackgroundTasks · `AnswerSynthesizer`
protocol / Null Object for the 501 slot · `FileStorage` port over
`DATA_DIR` (pathlib + one env var) · `KeywordIndex` protocol (one impl;
demoted to the concrete `Fts5Index` — the RRF symmetry it was meant to
protect is a shared `ScoredChunk` dataclass, not an interface) ·
`Retriever` protocol (one impl; it's a concrete service) · `GraphExporter`
protocol · ChunkingStrategy hierarchy · GoF State for the 4-state document
lifecycle (a str enum + one guarded UPDATE) · hexagonal `ports.py`
layering · parser auto-discovery · config framework (three env vars → one
frozen dataclass).

## 9. Error handling

- Ingestion failures never crash the service; the pipeline maps the typed
  `ParseError` taxonomy to readable reasons (encrypted PDF, corrupt file,
  empty text, unsupported content) and marks the document `failed`.
- Scanned/image-only PDFs raise `NoExtractableTextError` → "no extractable
  text (needs OCR)".
- Invalid FTS5 query syntax falls back to a plain-term query inside
  `Fts5Index`; searches never 500 on user input.
- Startup self-check = the composition root: migrations applied, embedding
  model loads (fail fast), FTS5 available, sqlite-vec probe result logged,
  stored embedding model/dim matches `EMBED_MODEL`.

## 10. Testing (TDD)

- **Parser unit tests** with tiny committed fixtures (2-page PDF, 3-slide
  PPTX, small DOCX/XLSX/CSV/MD) — highest-value tests; parsers are the
  flakiest layer. Includes the typed-error paths (encrypted, empty,
  image-only fixtures).
- **Vector contract suite:** one parametrized behavioral suite run against
  `SqliteVecIndex` *and* `NumpyVectorIndex` from Phase 1 (sqlite-vec *is*
  a test dependency). Pins cosine-similarity/higher-is-better ordering —
  the score-direction trap — before the fallback is ever needed.
- **Chunker tests:** boundaries, overlap, table row-grouping, location
  hints.
- **Search integration tests:** in-memory SQLite; ingest fixtures; assert
  known queries return expected chunks per mode; `rrf()` unit-tested
  directly as a pure function. Semantic tests assert rank presence, not
  exact scores. Fakes (`FakeEmbedder`) injected via `create_app` /
  `dependency_overrides` — no monkeypatching.
- **API tests** (FastAPI TestClient): upload → status `ready` (background
  tasks run synchronously under TestClient) → search → graph; failure
  paths (bad file, oversized, duplicate, bad query); single-transaction
  delete leaves no ghost rows in any of the four tables.
- **One real-model, real-sqlite-vec test runs inside the Docker image** —
  the steel-thread proof; it cannot be faked away.
- **`:memory:` footgun:** in-memory SQLite is per-connection; tests use
  one shared connection (or `file::memory:?cache=shared`) handed out by
  the injected connection factory. This workaround never leaks into
  production wiring.
- UI exercised manually in v1.

## 11. Implementation strategy — steel thread first

**Phase 1 is the POC, kept as real code:** minimal end-to-end slice —
upload one `.txt` → chunk → embed → index → hybrid search returns it —
running inside the target slim Docker image, with tests, wired through the
real `create_app` composition root (TxtParser only in the registry, real
fastembed, sqlite-vec with the numpy fallback behind the `VectorIndex`
probe). This proves the one integration that argument can't: fastembed +
sqlite-vec + FTS5 together in one image. The vector contract suite ships
in this phase.

Subsequent phases add parsers (one at a time, fixture-tested), the
similarity graph, and the UI — each independently testable.

## 12. Project layout

```
corpora/
├── app/
│   ├── main.py            # create_app() composition root + lifespan self-check
│   ├── models.py          # frozen dataclasses: ParsedDoc, TextBlock, Chunk, ScoredChunk, SearchHit
│   ├── api/               # routes: documents, search, graph, answer(501)
│   ├── ingest/            # parsers/ (one per format + registry), chunker, errors, validation, pipeline
│   ├── search/            # fts (Fts5Index), vectors (two impls + factory), rrf, service, embeddings
│   ├── graph/             # edges (incremental compute), export (2 serializers)
│   └── db.py              # SQLite schema, migrations, WAL/busy_timeout, transactional delete
├── static/                # index.html, app.js, styles.css, cytoscape
├── tests/  (+ fixtures/, contracts/)
├── Dockerfile             # single stage, slim, model baked in
├── docker-compose.yml     # local run with data volume
└── README.md
```

## 13. Future extensions (explicitly out of v1)

Each maps to a seam that already exists (§8) — none requires new v1 code
beyond what's specified:

- **LLM answer synthesis** — one synthesizer module filling the 501 slot;
  `SearchHit` already carries chunk text (free tiers: Groq / Gemini).
- **OCR for scanned PDFs** (pytesseract) — wraps the `pdf` registry entry,
  triggered by `NoExtractableTextError`; re-processes prior failures via
  the §3 re-ingest path.
- **Embedding model change** — `EMBED_MODEL` mismatch detected at startup
  via the `meta` table; corpus rebuilt via the re-ingest path.
- **Entity-level knowledge graph** (spaCy NER) — one new pipeline stage +
  new tables; reuses the neutral graph model and exporters.
- **Queue/worker + Postgres/pgvector** (Approach B) — worker calls
  `pipeline.ingest(document_id)` as-is; `PgVectorIndex` joins the vector
  contract suite; the rest is an intentional rewrite exercise.
- **Auth** — router-level `Depends` added in `create_app` + a migration
  adding owner columns; no placeholder user model in v1.
- **Persistence on ephemeral hosts** (HF Spaces + HF Dataset) — the seam
  is lifespan hooks (startup restore, periodic/shutdown sync with a WAL
  checkpoint before snapshot) around `DATA_DIR`, which already contains
  both the originals and the SQLite file.
