from __future__ import annotations
from typing import Protocol
from pathlib import Path
from app.models import ParsedDoc
from app.ingest.parsers.text import TextParser
from app.ingest.parsers.pdf import PdfParser
from app.ingest.parsers.docx import DocxParser
from app.ingest.parsers.pptx import PptxParser
from app.ingest.parsers.xlsx import XlsxParser
from app.ingest.parsers.csv import CsvParser


class Parser(Protocol):
    file_types: frozenset[str]
    def parse(self, path: Path) -> ParsedDoc: ...


def _build_registry(*parsers) -> dict[str, "Parser"]:
    reg: dict[str, Parser] = {}
    for p in parsers:
        for ft in p.file_types:
            reg[ft] = p
    return reg


PARSERS: dict[str, "Parser"] = _build_registry(
    TextParser(), PdfParser(), DocxParser(), PptxParser(), XlsxParser(), CsvParser())
