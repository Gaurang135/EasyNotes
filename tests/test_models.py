import dataclasses
import pytest
from app.models import TextBlock, ParsedDoc, Chunk, ScoredChunk, Status
from app.errors import ParseError, NoExtractableTextError


def test_textblock_is_frozen():
    b = TextBlock(text="hi", kind="prose", location="page 1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.text = "bye"  # type: ignore


def test_parseddoc_defaults():
    d = ParsedDoc(text_blocks=[], metadata={}, warnings=[])
    assert d.warnings == []


def test_status_values():
    assert Status.READY.value == "ready"


def test_error_hierarchy():
    assert issubclass(NoExtractableTextError, ParseError)


def test_scoredchunk_shape():
    s = ScoredChunk(chunk_id=1, score=0.9)
    assert s.chunk_id == 1 and s.score == 0.9
