from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Status(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


LocationHint = str  # e.g. "page 3", "slide 2", "Sheet1 rows 10-25"


@dataclass(frozen=True)
class TextBlock:
    text: str
    kind: Literal["prose", "table"] = "prose"
    location: LocationHint | None = None
    heading: str | None = None      # section heading path, for contextual headers


@dataclass(frozen=True)
class ParsedDoc:
    text_blocks: list[TextBlock]
    metadata: dict[str, str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    document_id: int
    seq: int
    text: str                       # raw text, for snippets/display
    embed_text: str                 # text actually embedded (may include header)
    location: LocationHint | None = None
    id: int | None = None           # set after DB insert


@dataclass(frozen=True)
class ScoredChunk:
    chunk_id: int
    score: float                    # higher-is-better, always


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    document_id: int
    document_title: str
    file_type: str
    snippet: str
    text: str                       # full chunk text (needed by future LLM slot)
    location: LocationHint | None
    score: float


@dataclass(frozen=True)
class SearchFilter:
    file_type: str | None = None
    doc_id: int | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass(frozen=True)
class Document:
    id: int
    filename: str
    title: str
    file_type: str
    size: int
    status: Status
    content_hash: str
    uploaded_at: str
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
