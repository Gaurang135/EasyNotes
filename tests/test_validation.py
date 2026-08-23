import zipfile
import pytest
from app.ingest import validation
from app.errors import UnsafeArchiveError


def test_sniff_rejects_zip_renamed_as_docx(tmp_path):
    fake = tmp_path / "evil.docx"
    with zipfile.ZipFile(fake, "w") as z:
        z.writestr("junk.txt", "not really a docx")
    # a plain zip must NOT be accepted as docx
    assert validation.sniff_type(fake, "evil.docx") != "docx"


def test_content_hash_is_stable(tmp_path):
    f = tmp_path / "a.txt"; f.write_text("abc")
    assert validation.content_hash(f) == validation.content_hash(f)


def test_zip_bomb_ratio_rejected(tmp_path):
    bomb = tmp_path / "b.xlsx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", b"0" * (60 * 1024 * 1024))  # 60MB uncompressed
    with pytest.raises(UnsafeArchiveError):
        validation.check_archive_safety(bomb, "xlsx")
