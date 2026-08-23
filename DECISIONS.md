# EasyNotes — Decision Log

A running log of *why* things are the way they are. Newest first.
Format: date · decision · reason · alternatives rejected.

## 2026-08-24 — Ingestion: single-worker queue + thread-local SQLite connections
A burst of ~75 concurrent uploads exposed two bugs: (1) fire-and-forget FastAPI
BackgroundTasks starved/dropped a task under threadpool pressure; (2) one shared
sqlite3 connection used from the worker + request threads raised "bad parameter or
other API misuse" (and 500s). Fix: a single-writer ingest queue (threaded worker in
prod, inline in tests) so every doc is processed once in order, and a ThreadLocalConn
proxy so each thread gets its own connection (WAL allows concurrent connections).
Verified: 80-file concurrent burst fully drains, 0 stuck, 0 500s. Pending docs are
re-enqueued on startup for crash recovery.

## 2026-08-24 — fastembed offline loading: HF_HUB_OFFLINE + cache_dir (not specific_model_path)
Discovered during the Docker build: `specific_model_path` does NOT bypass
fastembed 0.5.x's network-first check, so an offline container still tried to
download and failed. Fix: bake the model into an HF cache dir as the runtime
user, set `HF_HUB_OFFLINE=1` (after the build-time bake) and pass `cache_dir`.
Proven by `make docker-test` (boots + searches with `--network none`).

## 2026-08-24 — sqlite3.Connection needs a subclass to hold `vec_available`
Python 3.12's C-type Connection rejects arbitrary attributes; use a thin
`_Conn(sqlite3.Connection)` factory subclass. Caught by TDD on Task 3.

## 2026-08-24 — Name: EasyNotes
"Dump any file, find it in plain English." Friendly, low-friction feel.
Rejected: Corpora (too academic), Stash/Trove/Shoebox.

## 2026-08-24 — LLM-free (retrieval only)
No generation stage; `POST /answer` is a 501 slot. Reason: zero per-query
cost, fully self-hostable. LLM answer synthesis is a documented extension.

## 2026-08-24 — SQLite as the only store (FTS5 + sqlite-vec)
One file, no DB service to host, free-tier friendly. Needs no credentials
or server — SQLite is an embedded library, the "database" is just a file.
Rejected: Postgres/pgvector (that is the deferred "Approach B" rewrite).

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
