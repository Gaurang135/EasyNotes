from __future__ import annotations
import csv as _csv
from pathlib import Path
from app.models import ParsedDoc, TextBlock
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
        rows = [",".join(r) for r in _csv.reader(raw.splitlines(), dialect)]
        return ParsedDoc(text_blocks=[TextBlock(text="\n".join(rows), kind="table",
                                                location="rows")], metadata={}, warnings=[])
