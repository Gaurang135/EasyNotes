from __future__ import annotations
import csv as _csv
from pathlib import Path
from app.models import ParsedDoc, TextBlock, Table
from app.errors import EmptyDocumentError


class CsvParser:
    file_types = frozenset({"csv"})

    def parse(self, path: Path) -> ParsedDoc:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        if not raw.strip():
            raise EmptyDocumentError("file is empty")
        try:
            dialect = _csv.Sniffer().sniff(raw[:2048], delimiters=",;\t|")
        except _csv.Error:
            dialect = _csv.excel
        rows = [list(r) for r in _csv.reader(raw.splitlines(), dialect)]
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            raise EmptyDocumentError("no rows")
        columns, data = rows[0], rows[1:]
        text = "\n".join(",".join(r) for r in rows)
        tables = [Table(name="CSV", columns=columns, rows=data, location="rows")]
        return ParsedDoc(text_blocks=[TextBlock(text=text, kind="table", location="rows")],
                         metadata={}, warnings=[], tables=tables)
