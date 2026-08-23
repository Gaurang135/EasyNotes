from __future__ import annotations
from typing import Protocol
from pathlib import Path
from app.models import ParsedDoc
from app.ingest.parsers.text import TextParser


class Parser(Protocol):
    file_types: frozenset[str]
    def parse(self, path: Path) -> ParsedDoc: ...


def _build_registry(*parsers) -> dict[str, "Parser"]:
    reg: dict[str, Parser] = {}
    for p in parsers:
        for ft in p.file_types:
            reg[ft] = p
    return reg


# Parsers for pdf/docx/pptx/xlsx/csv are appended in Tasks 11-15.
PARSERS: dict[str, "Parser"] = _build_registry(TextParser())
