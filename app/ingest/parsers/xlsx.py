from __future__ import annotations
from pathlib import Path
from openpyxl import load_workbook
from app.models import ParsedDoc, TextBlock
from app.errors import CorruptFileError, NoExtractableTextError


class XlsxParser:
    file_types = frozenset({"xlsx"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            wb = load_workbook(str(path), read_only=True, data_only=True)
        except Exception as e:
            raise CorruptFileError(f"unreadable XLSX: {e}")
        blocks: list[TextBlock] = []
        try:
            for ws in wb.worksheets:
                rows = []
                for row in ws.iter_rows(values_only=True):
                    cells = ["" if v is None else str(v) for v in row]
                    if any(cells):
                        rows.append(",".join(cells))
                if rows:
                    blocks.append(TextBlock(text="\n".join(rows), kind="table",
                                            location=f"{ws.title} rows 1-{len(rows)}"))
        finally:
            wb.close()
        if not blocks:
            raise NoExtractableTextError("spreadsheet has no data")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
