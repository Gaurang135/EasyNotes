from pathlib import Path
import pytest
from app.ingest.parsers.pdf import PdfParser
from app.errors import EncryptedFileError


def test_pdf_extracts_text():
    doc = PdfParser().parse(Path("tests/fixtures/simple.pdf"))
    assert doc.text_blocks and doc.text_blocks[0].location == "page 1"
    assert "payments" in doc.text_blocks[0].text.lower()


def test_owner_password_pdf_still_parses():
    # empty user password -> must NOT be treated as encrypted
    doc = PdfParser().parse(Path("tests/fixtures/owner_locked.pdf"))
    assert doc.text_blocks


def test_user_password_pdf_raises_encrypted():
    with pytest.raises(EncryptedFileError):
        PdfParser().parse(Path("tests/fixtures/user_locked.pdf"))
