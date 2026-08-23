from __future__ import annotations
from pathlib import Path
from app.models import ParsedDoc, TextBlock
from app.errors import EmptyDocumentError


class TextParser:
    file_types = frozenset({"txt", "md"})

    def parse(self, path: Path) -> ParsedDoc:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            raise EmptyDocumentError("file is empty")
        blocks: list[TextBlock] = []
        current_heading = None
        buf: list[str] = []

        def flush():
            if buf:
                blocks.append(TextBlock(text="\n".join(buf).strip(),
                                        kind="prose", heading=current_heading))
                buf.clear()

        for line in raw.splitlines():
            if line.startswith("#"):
                flush()
                current_heading = line.lstrip("#").strip()
            else:
                buf.append(line)
        flush()
        if not blocks:
            blocks = [TextBlock(text=raw, kind="prose")]
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
