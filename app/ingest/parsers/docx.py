from __future__ import annotations
from pathlib import Path
from docx import Document as Docx
from docx.text.paragraph import Paragraph
from docx.table import Table
from app.models import ParsedDoc, TextBlock
from app.errors import CorruptFileError, NoExtractableTextError


class DocxParser:
    file_types = frozenset({"docx"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            d = Docx(str(path))
        except Exception as e:
            raise CorruptFileError(f"unreadable DOCX: {e}")
        blocks: list[TextBlock] = []
        heading = None
        for item in d.iter_inner_content():          # preserves interleaved order
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                if item.style and item.style.name and item.style.name.startswith("Heading"):
                    heading = text
                blocks.append(TextBlock(text=text, kind="prose", heading=heading))
            elif isinstance(item, Table):
                rows = ["\t".join(c.text for c in row.cells) for row in item.rows]
                if rows:
                    blocks.append(TextBlock(text="\n".join(rows), kind="table", heading=heading))
        if not blocks:
            raise NoExtractableTextError("no extractable text")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
