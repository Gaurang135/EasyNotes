from __future__ import annotations
from pathlib import Path
from docx import Document as Docx
from docx.text.paragraph import Paragraph
from docx.table import Table
from app.models import ParsedDoc, TextBlock, Table as DocTable
from app.errors import CorruptFileError, NoExtractableTextError


class DocxParser:
    file_types = frozenset({"docx"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            d = Docx(str(path))
        except Exception as e:
            raise CorruptFileError(f"unreadable DOCX: {e}")
        blocks: list[TextBlock] = []
        tables: list[DocTable] = []
        heading = None
        tnum = 0
        for item in d.iter_inner_content():          # preserves interleaved order
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                if item.style and item.style.name and item.style.name.startswith("Heading"):
                    heading = text
                blocks.append(TextBlock(text=text, kind="prose", heading=heading))
            elif isinstance(item, Table):
                grid = [[c.text.strip() for c in row.cells] for row in item.rows]
                grid = [r for r in grid if any(r)]
                if grid:
                    blocks.append(TextBlock(text="\n".join("\t".join(r) for r in grid),
                                            kind="table", heading=heading))
                    tnum += 1
                    tables.append(DocTable(name=heading or f"Table {tnum}",
                                           columns=grid[0], rows=grid[1:], location=heading))
        if not blocks:
            raise NoExtractableTextError("no extractable text")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[], tables=tables)
