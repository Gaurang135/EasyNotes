"""HTML parser — extracts readable text (scripts/styles stripped) as searchable prose and
turns every <table> into a structured, queryable Table. Uses lxml's forgiving HTML parser,
so malformed and deeply nested markup (including nested tables) parses without breaking.
"""
from __future__ import annotations
from pathlib import Path
import lxml.html
from lxml import etree
from app.models import ParsedDoc, TextBlock, Table
from app.errors import CorruptFileError, EmptyDocumentError, NoExtractableTextError


def _table_to_grid(tbl) -> list[list[str]]:
    """Rows that belong to THIS table (a nested table's own rows are handled when it is
    visited separately); a nested table inside a cell is flattened into that cell's text."""
    rows = tbl.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr") or tbl.xpath(".//tr")
    grid = []
    for tr in rows:
        cells = [" ".join(c.text_content().split()) for c in tr.xpath("./th | ./td")]
        if any(cells):
            grid.append(cells)
    if grid:                                   # pad ragged rows to a rectangle
        w = max(len(r) for r in grid)
        grid = [r + [""] * (w - len(r)) for r in grid]
    return grid


class HtmlParser:
    file_types = frozenset({"html", "htm"})

    def parse(self, path: Path) -> ParsedDoc:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        if not raw.strip():
            raise EmptyDocumentError("file is empty")
        try:
            tree = lxml.html.fromstring(raw)
        except (etree.ParserError, etree.XMLSyntaxError, ValueError) as e:
            raise CorruptFileError(f"unreadable HTML: {e}")

        title_el = tree.find(".//title")
        title = title_el.text.strip() if title_el is not None and title_el.text else None
        for junk in tree.xpath("//script | //style | //noscript"):
            junk.getparent().remove(junk)

        blocks: list[TextBlock] = []
        tables: list[Table] = []
        table_els = tree.xpath("//table")
        for i, tbl in enumerate(table_els, 1):
            grid = _table_to_grid(tbl)
            if not grid:
                continue
            cols, rows = grid[0], grid[1:]
            tables.append(Table(name=title or f"Table {i}", columns=cols, rows=rows,
                                location=f"table {i}"))
            blocks.append(TextBlock(text="\n".join("\t".join(r) for r in grid),
                                    kind="table", location=f"table {i}"))
        # drop tables from the tree so their text isn't duplicated in the prose block
        for tbl in table_els:
            p = tbl.getparent()
            if p is not None:
                p.remove(tbl)

        text = "\n".join(ln.strip() for ln in tree.text_content().splitlines() if ln.strip())
        if text:
            blocks.insert(0, TextBlock(text=text, kind="prose", location="body", heading=title))
        if not blocks:
            raise NoExtractableTextError("no extractable text")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[], tables=tables)
