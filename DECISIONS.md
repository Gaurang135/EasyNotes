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
