"""JSON parser — turns semi-structured JSON into the same structured shape as everything
else: arrays of records become queryable Tables, and scalar values (however deeply nested)
become flattened `dot.path: value` prose so search and field extraction work on them.

Handles complex/nested structures: an object holding both metadata and a nested array of
records yields the metadata as fields AND the array as a table; nested objects/arrays that
sit inside a table cell are preserved as compact JSON rather than dropped.
"""
from __future__ import annotations
import json
from pathlib import Path
from app.models import ParsedDoc, TextBlock, Table
from app.errors import CorruptFileError, EmptyDocumentError


def _stringify(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):        # keep nested structure rather than lose it
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def _is_record_array(v) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(isinstance(x, dict) for x in v)


def _array_to_table(records: list[dict], name: str) -> Table:
    cols: list[str] = []
    for rec in records:                    # ordered union of keys across all records
        for k in rec:
            if k not in cols:
                cols.append(k)
    rows = [[_stringify(rec.get(c, "")) for c in cols] for rec in records]
    return Table(name=name, columns=[str(c) for c in cols], rows=rows, location=name)


def _walk(obj, prefix: str, pairs: list, tables: list) -> None:
    """Collect scalar (key, value) pairs and record-array tables from anywhere in the tree."""
    if _is_record_array(obj):
        tables.append(_array_to_table(obj, prefix.rstrip(".") or "records"))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}"
            if _is_record_array(v):
                tables.append(_array_to_table(v, key))
            elif isinstance(v, dict):
                _walk(v, key + ".", pairs, tables)
            elif isinstance(v, list):
                if any(isinstance(x, (dict, list)) for x in v):
                    for i, x in enumerate(v):
                        _walk(x, f"{key}[{i}].", pairs, tables)
                else:                       # array of scalars → one joined value
                    pairs.append((key, ", ".join(_stringify(x) for x in v)))
            else:
                pairs.append((key, _stringify(v)))
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            _walk(x, f"{prefix}[{i}].", pairs, tables)
    else:
        pairs.append((prefix.rstrip(".") or "value", _stringify(obj)))


class JsonParser:
    file_types = frozenset({"json"})

    def parse(self, path: Path) -> ParsedDoc:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        if not raw.strip():
            raise EmptyDocumentError("file is empty")
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            raise CorruptFileError(f"invalid JSON: {e}")
        pairs: list = []
        tables: list = []
        _walk(data, "", pairs, tables)
        blocks: list[TextBlock] = []
        prose = "\n".join(f"{k}: {v}" for k, v in pairs if v != "")
        if prose:
            blocks.append(TextBlock(text=prose, kind="prose", location="json"))
        for t in tables:
            rows_text = "\n".join("\t".join(r) for r in ([t.columns] + t.rows))
            blocks.append(TextBlock(text=rows_text, kind="table", location=t.name))
        if not blocks:
            raise EmptyDocumentError("no data found in JSON")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[], tables=tables)
