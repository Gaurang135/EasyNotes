from __future__ import annotations
import csv as _csv
from pathlib import Path
from app.models import ParsedDoc, TextBlock, Table
from app.errors import EmptyDocumentError
from app.ingest.extract import infer_column_type


def _has_header(rows: list[list[str]]) -> bool:
    """Heuristic: does the first row label the columns, or is it data?

    A label row is text sitting above columns whose data is numeric/date. So if, for the
    columns whose data is numeric/date, the first row already looks like that same type,
    the first row is data — there is no header. When every column is text the two are
    indistinguishable (a text header looks like a text row), so we default to "has header",
    matching csv.Sniffer and the fact that most CSVs are written with one."""
    if len(rows) < 2:
        return True
    first, rest = rows[0], rows[1:]
    typed_cols = matches_data = 0
    width = max(len(r) for r in rows)
    for i in range(width):
        vals = [r[i].strip() for r in rest if i < len(r) and r[i].strip()]
        if not vals:
            continue
        col_type = infer_column_type(vals)
        if col_type == "text":
            continue                              # can't disambiguate on a text column
        typed_cols += 1
        cell = first[i].strip() if i < len(first) else ""
        if cell and infer_column_type([cell]) == col_type:
            matches_data += 1                     # first row is the same type as the data below
    # no header only when there ARE typed columns and the first row matches data in all of them
    return not (typed_cols > 0 and matches_data == typed_cols)


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
        warnings = []
        if _has_header(rows):
            columns, data = rows[0], rows[1:]
        else:
            # headerless: synthesize names so no data row is consumed as labels (and lost)
            columns = [f"Column {i+1}" for i in range(max(len(r) for r in rows))]
            data = rows
            warnings.append("no header row detected — columns auto-named Column 1..N")
        text = "\n".join(",".join(r) for r in rows)
        tables = [Table(name="CSV", columns=columns, rows=data, location="rows")]
        return ParsedDoc(text_blocks=[TextBlock(text=text, kind="table", location="rows")],
                         metadata={}, warnings=warnings, tables=tables)
