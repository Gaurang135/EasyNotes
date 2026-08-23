from __future__ import annotations
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from app.models import ParsedDoc, TextBlock
from app.errors import EncryptedFileError, CorruptFileError, NoExtractableTextError


class PdfParser:
    file_types = frozenset({"pdf"})

    def parse(self, path: Path) -> ParsedDoc:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                # owner-password-only PDFs decrypt with an empty user password
                if reader.decrypt("") == 0:
                    raise EncryptedFileError("PDF requires a password")
            blocks, warnings = [], []
            for i, page in enumerate(reader.pages):
                try:
                    text = (page.extract_text() or "").strip()
                except Exception:
                    warnings.append(f"page {i+1}: extraction failed"); continue
                if text:
                    blocks.append(TextBlock(text=text, kind="prose", location=f"page {i+1}"))
            if not blocks:
                raise NoExtractableTextError("no extractable text (needs OCR)")
            return ParsedDoc(text_blocks=blocks, metadata={}, warnings=warnings)
        except (PdfReadError, OSError) as e:
            raise CorruptFileError(f"unreadable PDF: {e}")
