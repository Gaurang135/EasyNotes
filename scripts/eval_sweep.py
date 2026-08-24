"""Diagnostic retrieval/answer sweep against the LIVE corpus.

Each case: a realistic question + the document title-substring that SHOULD surface.
Retrieval cases assert the expected doc appears in the top-K hybrid hits (deterministic,
no LLM). A few answer cases check the grounded answer isn't a false 'not found'.
"""
import json, sys, time, urllib.request

BASE = "http://localhost:8000"
TOPK = 5


def search(q, mode="hybrid"):
    u = f"{BASE}/search?q={urllib.request.quote(q)}&mode={mode}"
    return json.loads(urllib.request.urlopen(u, timeout=30).read())["results"]


def answer(q):
    req = urllib.request.Request(f"{BASE}/answer",
        data=json.dumps({"q": q}).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=90).read())


# (query, expected-title-substring, intent, doc-type)
RETRIEVAL = [
    ("who is free", "sun", "narrative", "txt"),
    ("man in a long coat in the park", "sun", "narrative", "txt"),
    ("what does the book excerpt say", "Book Excerpt", "narrative", "txt"),
    ("vendor on invoice_07", "invoice_07", "entity", "txt"),
    ("acme contract terms", "Acme Contract", "entity", "txt"),
    ("globex purchase order", "Globex PO", "entity", "txt"),
    ("acme receipt", "Acme Receipt", "entity", "txt"),
    ("customers on the free plan", "customers", "table", "csv"),
    ("employee list", "employees", "table", "csv"),
    ("shipments tracking", "shipments", "table", "csv"),
    ("support tickets", "support_tickets", "table", "csv"),
    ("sales figures", "sales", "table", "csv"),
    ("inventory stock levels", "inventory", "table", "csv"),
    ("leads pipeline", "leads", "table", "csv"),
    ("expenses breakdown", "expenses", "table", "csv"),
    ("annual budget", "budget", "table", "xlsx"),
    ("payroll", "payroll", "table", "xlsx"),
    ("kpis metrics", "kpis", "table", "xlsx"),
    ("financial statements", "financials", "table", "xlsx"),
    ("checkout testing architecture", "Checkout Testing", "deck", "pptx"),
    ("tax compliance checkout discussion", "Tax-compliance", "notes", "docx"),
    ("technical specification", "spec", "spec", "md"),
    ("resume candidate experience", "resume", "entity", "txt"),
    ("company policy", "policy", "entity", "txt"),
    ("team meeting notes", "Team Notes", "entity", "txt"),
    ("q1 meeting", "meeting_q1", "entity", "txt"),
    ("memo", "memo", "entity", "txt"),
]

# (query, must NOT be a false 'not found', label)
ANSWERS = [
    ("who becomes free in the sun story", "sun"),
    ("how many invoices do we have", "count"),
    ("what all items did i buy", "items"),
    ("list the distinct companies", "companies"),
]


def run():
    fails = []
    print(f"{'RESULT':6} {'RANK':4} {'INTENT':9} {'TYPE':5} QUERY -> EXPECTED")
    print("-" * 78)
    for q, expect, intent, dt in RETRIEVAL:
        try:
            hits = search(q)
        except Exception as e:
            print(f"{'ERR':6} {'-':4} {intent:9} {dt:5} {q!r}: {e}"); fails.append(q); continue
        rank = next((i + 1 for i, h in enumerate(hits[:TOPK])
                     if expect.lower() in h["document_title"].lower()), None)
        ok = rank is not None
        top = hits[0]["document_title"][:28] if hits else "(none)"
        print(f"{'PASS' if ok else 'FAIL':6} {str(rank or '-'):4} {intent:9} {dt:5} {q!r} -> {expect!r}"
              + ("" if ok else f"   [top: {top}]"))
        if not ok:
            fails.append((q, expect, top))
    print("\n--- ANSWER (false-not-found check) ---")
    for q, label in ANSWERS:
        try:
            d = answer(q)
            a = d.get("answer", "")
            bad = "couldn't find" in a.lower() or "could not find" in a.lower()
            print(f"{'FAIL' if bad else 'PASS':6} {label:10} {q!r} -> {a[:60].strip()!r}")
            if bad:
                fails.append((q, label, a[:40]))
        except Exception as e:
            print(f"{'ERR':6} {label:10} {q!r}: {e}")
        time.sleep(7)  # respect free-tier rate limit
    print(f"\n{'='*40}\nRETRIEVAL+ANSWER FAILURES: {len(fails)}")
    for f in fails:
        print("  ", f)
    return len(fails)


sys.exit(1 if run() else 0)
