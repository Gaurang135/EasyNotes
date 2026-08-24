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

# Invoice/receipt line items hide inside a messy run like
#   "Line items: Cog x8 Rs.557.17 Gadget x18 Rs.278.75 Subtotal Rs.2324,000.00"
# A line item is a product name followed by a quantity ("xN") and a price; the "xN"
# marker is what distinguishes a purchased item from a Subtotal/Tax/Total line.
_AMOUNT = r"(?:₹|\$|€|£|Rs\.?|INR|USD|EUR)\s?\d[\d,]*(?:\.\d{1,2})?"
_LINE_ITEM = re.compile(rf"([A-Za-z][A-Za-z0-9 \-]*?)\s+[x×](\d+)\s+({_AMOUNT})")

# "Key: value" pairs on a single line (label of 1-40 chars). Separator is a SINGLE colon
# only — never a hyphen — because hyphens are ubiquitous in prose, code and diagrams
# ("A --> B", "User-Agent", "total - 1"), which is what previously flooded the field set
# with junk. "::" / ":=" (namespaces, assignment) are excluded via the negative lookahead.
_PAIR = re.compile(r"^[ \t]*([A-Za-z][\w \-/]{1,39})[ \t]*:(?![:=])[ \t]*(.+?)[ \t]*$", re.MULTILINE)

# Tokens that mark a "pair" as really code/diagram/markup, not a human key:value fact.
_NOT_A_FACT = re.compile(r"[|<>{}\[\]`]|-->|-\|>|-\.->|==>|->|::|:=|&&")

# Fenced code blocks and diagram/code lines are stripped before pair-scanning so a
# document that embeds a Mermaid diagram or code snippet can't spawn junk "facts".
# (Typed rules — email/amount/date/… — still run over the full text.)
_FENCE = re.compile(r"```.*?```", re.S)
_DIAGRAM_LINE = re.compile(
    r"^\s*(graph|flowchart|sequenceDiagram|classDiagram|erDiagram|stateDiagram|gantt|"
    r"subgraph|style|classDef|class|linkStyle|participant|actor|note (?:over|left|right))\b", re.I)
_ARROW_LINE = re.compile(r"-->|-\.->|==>|-\|>|\|>|--\||~~~|→|←|⟶")


def _prose_for_pairs(text: str) -> str:
    """Text with fenced code and diagram/arrow lines removed — the safe input for
    key:value pair extraction (which is otherwise easily fooled by code/diagrams)."""
    text = _FENCE.sub(" ", text)
    return "\n".join(ln for ln in text.splitlines()
                     if not _DIAGRAM_LINE.search(ln) and not _ARROW_LINE.search(ln))


def _looks_like_pair(key: str, value: str) -> bool:
    """Reject key:value 'facts' that are actually code, diagram edges or punctuation noise."""
    if _NOT_A_FACT.search(key) or _NOT_A_FACT.search(value):
        return False
    if not re.search(r"[A-Za-z0-9]", value):            # a real value has an alphanumeric run
        return False
    keep = sum(c.isalnum() or c.isspace() for c in value)
    return keep / len(value) >= 0.4                      # not mostly punctuation

_DATE_RE = re.compile(RULES[3]["pattern"])
_NUM_RE = re.compile(r"^[+-]?[\d,]*\.?\d+%?$")


def extract_fields(text: str, limit: int = 200) -> list[Field]:
    """Pull structured key-value facts from free text. Deduplicated, order-stable."""
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    typed_values: set[str] = set()          # values already captured as a typed field
    out: list[Field] = []

    def add(key: str, value: str, kind: str):
        value = value.strip()
        if not value:
            return
        # named fields (pair/item) are unique per (label, value); typed fields per value
        sig = (kind, key.lower(), value.lower()) if kind in ("pair", "item") else (kind, value.lower())
        if sig in seen:
            return
        seen.add(sig)
        if kind not in ("pair", "item"):
            typed_values.add(value.lower())
        out.append(Field(key=key, value=value, kind=kind))

    for kind, rx in _COMPILED:
        for m in rx.findall(text):
            add(kind, m if isinstance(m, str) else m[0], kind)
            if len(out) >= limit:
                return out
    # line items: product name + quantity + price (e.g. "Cog x8 Rs.557.17")
    for name, qty, amount in _LINE_ITEM.findall(text):
        add(name.strip(), f"×{qty} · {amount}", "item")
        if len(out) >= limit:
            return out
    _SCHEMES = {"http", "https", "ftp", "mailto", "tel"}
    for key, val in _PAIR.findall(_prose_for_pairs(text)):
        k = key.strip()
        # skip URL/scheme false positives ("https://..." parses as https : //...)
        if k.lower() in _SCHEMES or val.startswith("//"):
            continue
        # skip a pair whose value is already a typed field (e.g. "Date: 2026-03-20")
        if val.strip().lower() in typed_values:
            continue
        # skip code/diagram/punctuation noise masquerading as a fact
        if not _looks_like_pair(k, val.strip()):
            continue
        if len(val) <= 120:
            add(k, val, "pair")
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
