from __future__ import annotations
from pathlib import Path
from pptx import Presentation
from app.models import ParsedDoc, TextBlock
from app.errors import CorruptFileError, NoExtractableTextError


def _iter_text(shapes):
    for shape in shapes:
        if shape.shape_type == 6:  # GROUP — recurse
            yield from _iter_text(shape.shapes)
        elif shape.has_text_frame:
            t = shape.text_frame.text.strip()
            if t:
                yield t


class PptxParser:
    file_types = frozenset({"pptx"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            prs = Presentation(str(path))
        except Exception as e:
            raise CorruptFileError(f"unreadable PPTX: {e}")
        blocks: list[TextBlock] = []
        for i, slide in enumerate(prs.slides, 1):
            title = slide.shapes.title.text.strip() if slide.shapes.title else None
            body = list(_iter_text(slide.shapes))
            if body:
                blocks.append(TextBlock(text="\n".join(body), kind="prose",
                                        location=f"slide {i}", heading=title))
            # notes: access .notes_slide only if present (accessing it CREATES one)
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    blocks.append(TextBlock(text=notes, kind="prose",
                                            location=f"slide {i} notes", heading=title))
        if not blocks:
            raise NoExtractableTextError("no extractable text")
        return ParsedDoc(text_blocks=blocks, metadata={}, warnings=[])
