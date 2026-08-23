from __future__ import annotations
import hashlib
import zipfile
from pathlib import Path
from app.errors import UnsafeArchiveError, CorruptFileError

_OOXML = {"docx", "xlsx", "pptx"}
_MAX_UNCOMPRESSED = 250 * 1024 * 1024
_MAX_RATIO = 100
_MAX_ENTRIES = 10_000
_MAX_SHAREDSTRINGS = 50 * 1024 * 1024


def content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def check_size(path: Path, max_mb: int) -> None:
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise CorruptFileError(f"file exceeds {max_mb}MB limit")


def sniff_type(path: Path, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _OOXML:
        # OOXML are zips; confirm the right content type is inside
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
            markers = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}
            if any(n.startswith(markers[ext]) for n in names):
                return ext
            return "zip"  # a plain zip masquerading as OOXML
        except zipfile.BadZipFile:
            return "unknown"
    return ext or "unknown"


def check_archive_safety(path: Path, file_type: str) -> None:
    if file_type not in _OOXML:
        return
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > _MAX_ENTRIES:
                raise UnsafeArchiveError("archive has too many entries")
            total = 0
            for info in infos:
                total += info.file_size
                if info.compress_size and info.file_size / max(info.compress_size, 1) > _MAX_RATIO:
                    raise UnsafeArchiveError("archive compression ratio too high")
                if info.filename.endswith("sharedStrings.xml") and info.file_size > _MAX_SHAREDSTRINGS:
                    raise UnsafeArchiveError("spreadsheet is too text-heavy")
            if total > _MAX_UNCOMPRESSED:
                raise UnsafeArchiveError("archive uncompressed size too large")
    except zipfile.BadZipFile:
        raise CorruptFileError("not a valid office file")
