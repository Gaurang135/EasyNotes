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
        with TestClient(create_app(Settings.from_env(overrides={"DATA_DIR": d}))) as client:
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
