"""Config-driven field extraction + column type inference.

Inspired by Razorpay's `billme-parser-worker`, which runs config/regex-driven
parsers over messy text to pull structured fields — rather than hand-coding a
parser per format. Add a new field type by appending one rule to RULES.
"""
from __future__ import annotations
import re
from app.models import Field

# --- config-driven extraction rules: {kind, pattern} ---------------------------
RULES: list[dict] = [
    {"kind": "email", "pattern": r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"},
    {"kind": "url", "pattern": r"https?://[^\s)>\]]+"},
    {"kind": "amount", "pattern": r"(?:₹|\$|€|£|Rs\.?|INR|USD|EUR)\s?\d[\d,]*(?:\.\d{1,2})?"},
    {"kind": "date", "pattern": r"\b\d{4}-\d{2}-\d{2}\b"
                                r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
                                r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b"},
    {"kind": "phone", "pattern": r"(?<!\d)(?:\+\d{1,3}[\s-]?)?(?:\d[\s-]?){9,12}\d(?!\d)"},
]
_COMPILED = [(r["kind"], re.compile(r["pattern"])) for r in RULES]

# "Key: value" pairs on a single line (label of 1-40 chars, letters/spaces/-/_)
_PAIR = re.compile(r"^[ \t]*([A-Za-z][\w \-/]{1,39})[ \t]*[:\-][ \t]*(.+?)[ \t]*$", re.MULTILINE)

_DATE_RE = re.compile(RULES[3]["pattern"])
_NUM_RE = re.compile(r"^[+-]?[\d,]*\.?\d+%?$")


def extract_fields(text: str, limit: int = 200) -> list[Field]:
    """Pull structured key-value facts from free text. Deduplicated, order-stable."""
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[Field] = []

    def add(key: str, value: str, kind: str):
        value = value.strip()
        if not value:
            return
        sig = (kind, value.lower())
        if sig in seen:
            return
        seen.add(sig)
        out.append(Field(key=key, value=value, kind=kind))

    for kind, rx in _COMPILED:
        for m in rx.findall(text):
            add(kind, m if isinstance(m, str) else m[0], kind)
            if len(out) >= limit:
                return out
    for key, val in _PAIR.findall(text):
        # skip pairs already captured as a typed field (e.g. "Email: x@y.com")
        if len(val) <= 120:
            add(key.strip(), val, "pair")
            if len(out) >= limit:
                break
    return out


def infer_column_type(values: list[str]) -> str:
    """Best-effort type for a table column: number | date | text."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return "text"
    if all(_NUM_RE.match(v.replace(" ", "")) for v in vals):
        return "number"
    if all(_DATE_RE.search(v) for v in vals):
        return "date"
    return "text"
