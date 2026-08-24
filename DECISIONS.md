# EasyNotes — Decisions

Why the project is built the way it is — the choices I made and the reasoning behind them,
grouped by area.

## Language & stack
- **Chose Python as the core language** mainly for the ecosystem: it has the richest set of
  self-contained document parsers (pypdf, python-docx, python-pptx, openpyxl, lxml) *and* a
  local embedding runtime (fastembed/ONNX). Go or Node would have forced me onto hosted APIs
  for parsing/embeddings, which breaks the offline, zero-cost goal.
- **Used FastAPI on a single uvicorn process** — typed request validation with little
  boilerplate, and it runs comfortably in a 512 MB free tier. I deliberately kept it to one
  process: multiple workers would each load their own copy of the embedding model (memory
  blow-up) and each become a separate SQLite writer.
- **Added abstractions only where they earn their place** — an interface exists only where
  there's a real second implementation or a testing need (parser, vector index, embedder,
  snapshot backend). No ORM/repository layer or speculative interfaces.

## Storage & data
- **Used SQLite as the only datastore** so there's no separate DB instance to run or
  credentials to manage — it ships inside the same Docker image as a single file. Keyword
  search (FTS5), vectors (sqlite-vec), and the extracted tables/fields all live in that one
  file, so everything backs up and restores together. (Postgres/pgvector is the obvious
  scale-up path if it ever outgrows one node.)
- **Made vector search degrade to a numpy cosine scan** if sqlite-vec (still pre-1.0) can't
  load, so search always works instead of being a hard dependency.
- **Gave each thread its own SQLite connection (WAL mode)** after a burst of concurrent
  uploads sharing one connection caused "API misuse" errors.
- **Deduplicated by file content hash** — re-uploading the same file returns the existing
  document instead of ingesting it twice.

## Ingestion & reliability
- **Process uploads through a single background worker, one at a time.** Fire-and-forget
  background tasks dropped work under load; a single-writer queue processes every document
  exactly once, in order, and re-queues anything left unfinished after a restart.
- **Validate before parsing** — a size cap plus zip-bomb / malicious-archive checks for
  Office files, so one bad or huge upload can't take the service down.

## Search
- **Built hybrid search** that fuses three signals — exact keyword (FTS5/BM25), meaning
  (embeddings), and a document-title match — with Reciprocal Rank Fusion. Keyword alone
  misses paraphrases, meaning alone misses exact IDs and ignores filenames; together they
  cover both. (The title leg was added after documents kept being unfindable by their name.)
- **Ran embeddings locally (BAAI/bge-small) via fastembed**, offline — no embedding API, no
  per-query cost, works with the network switched off.

## Extraction
- **Kept extraction deterministic (rules/regex), not an LLM.** It's exact, free, offline, and
  can't hallucinate a value that isn't in the document — and extraction *is* the core of the
  problem, so correctness matters more than cleverness.
- **Parsed key:value pairs on a colon only (never a hyphen) and skip code/diagram blocks**,
  after a document containing a Mermaid diagram produced ~80 junk "fields."
- **Handled the messy real-world cases** — invoice line items, headerless CSVs, nested JSON,
  and HTML tables — so those become clean tables/fields instead of being dropped or mangled.
- **Made OCR opt-in** (a flag + separate install) so the default stays lean, but scanned/image
  documents can still be read.

## LLM / Ask (optional)
- **Kept the core LLM-free and made grounded "Ask" an optional add-on.** Retrieval,
  extraction, and the Data views need no model and cost nothing; Ask plugs into a
  provider-agnostic seam (any OpenAI-compatible endpoint) and stays off until a key is set.
- **Chose Gemini 3.1 Flash-Lite (free tier) for Ask.** I compared providers on price,
  throughput (TPS/RPM) and daily limits (RPD): Groq's free tier rate-limited too aggressively
  for testing; OpenAI's GPT-5.x tiers are paid; and within Gemini's free models the newest
  (3.7 Flash) was capacity-limited and returned 503s on real payloads, while full Flash has a
  lower daily cap. Flash-Lite gives the highest free-tier throughput and RPD — which matters
  if a reviewer tests it hard — and since it's an OpenAI-compatible endpoint, switching model
  or provider is a one-line env change.
- **Kept counts and totals out of the model.** Aggregate questions ("how many", "total") are
  answered from a whole-library structured summary, and the Insights are computed in code — so
  the model is used for language, never for arithmetic, where it can quietly slip.
- **Chose the Ask system prompt by A/B test, not intuition.** I wrote 7 prompt variants and
  ran all of them against the same seeded library and the same 6 ground-truthed questions
  through the real model, then had a panel of four different judge models score every answer
  on accuracy, citation grounding, honest refusals, formatting, and — crucially — whether any
  internal wording leaked into the reply. The winner combined strict one-item-per-line cited
  lists with an explicit ban on ever surfacing internal labels to the user. This also fixed a
  real bug: answers used to echo the injected context and say things like "6 documents in the
  corpus inventory"; the shipped prompt refers only to "your documents", and I renamed that
  context block accordingly.

## UI / UX
- **Four tabs — Search, Library, Data, Add** — with Search as the landing page that doubles as
  a dashboard.
- **Made the Data tab show records, not a BI dashboard.** I first built spend charts, then
  removed them: the brief is "structured, queryable data," not analytics, and the charts broke
  on non-invoice data. Each document now shows what was extracted from it, with search and
  filters across everything.
- **Added a light/dark toggle that defaults to the OS setting**, remembers the choice, and
  doesn't flash on load.
- **Added one-click sample data.** Since the database isn't committed, a fresh clone opens
  empty, so a "Load sample data" button (shown only when there's nothing yet) populates a demo
  library instantly.

## Deployment & testing
- **Targeted $0 hosting — Render free tier + Cloudflare R2.** The free disk is ephemeral, so
  the database is snapshotted to R2 and restored on boot.
- **Proved the offline claim** with a Docker test that runs a real ingest + search with the
  network disabled.
- **Wrote tests first throughout**, with fast network-free fakes for the embedder and the LLM
  so the suite stays deterministic.
- **Kept secrets in a gitignored `.env`** — never committed.
