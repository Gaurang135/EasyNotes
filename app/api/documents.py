from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app import db, store
from app.models import Status
from app.ingest import validation
from app.errors import CorruptFileError
from app.api.deps import get_state
from app.api.schemas import DocumentOut, DocumentInfo

router = APIRouter()


class PasteText(BaseModel):
    title: str
    text: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _create_row(state, filename, title, file_type, size, chash) -> int:
    cur = state.conn.execute(
        "INSERT INTO documents(filename,title,file_type,size,status,content_hash,uploaded_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (filename, title, file_type, size, Status.PENDING.value, chash, _now()))
    state.conn.commit()
    return cur.lastrowid


def _ingest_bytes(state, filename: str, data: bytes) -> dict:
    """Validate, dedupe, persist and enqueue one file. Shared by upload and seed."""
    originals = Path(state.settings.data_dir) / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    tmp = originals / f"_tmp_{filename}"
    tmp.write_bytes(data)
    try:
        validation.check_size(tmp, state.settings.max_upload_mb)
    except CorruptFileError as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(413, str(e))
    ftype = validation.sniff_type(tmp, filename)
    if ftype not in state.parsers:
        tmp.unlink(missing_ok=True)
        raise HTTPException(415, f"unsupported file type: {ftype}")
    chash = validation.content_hash(tmp)
    existing = state.conn.execute("SELECT id FROM documents WHERE content_hash=?", (chash,)).fetchone()
    if existing:
        tmp.unlink(missing_ok=True)
        return {"id": existing[0], "status": "duplicate"}
    title = filename.rsplit(".", 1)[0]
    doc_id = _create_row(state, filename, title, ftype, tmp.stat().st_size, chash)
    tmp.rename(originals / f"{doc_id}_{filename}")
    state.ingest.enqueue(doc_id)
    return {"id": doc_id, "status": "pending"}


@router.post("/documents", status_code=201)
def upload(response: Response, file: UploadFile = File(...), state=Depends(get_state)):
    result = _ingest_bytes(state, file.filename or "untitled", file.file.read())
    if result.get("status") == "duplicate":     # nothing was created → 200, not 201
        response.status_code = status.HTTP_200_OK
    return result


_SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


@router.post("/documents/seed")
def seed(state=Depends(get_state)):
    """Populate an EMPTY corpus with a small, varied demo set (only when empty, so a
    fresh clone shows a populated app in one click)."""
    if state.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]:
        raise HTTPException(409, "corpus is not empty — seed only runs on an empty corpus")
    if not _SAMPLES_DIR.is_dir():
        raise HTTPException(500, "no sample data bundled")
    added = 0
    for p in sorted(_SAMPLES_DIR.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            try:
                if _ingest_bytes(state, p.name, p.read_bytes())["status"] != "duplicate":
                    added += 1
            except HTTPException:
                continue
    return {"added": added}


@router.post("/documents/text", status_code=201)
def paste(body: PasteText, state=Depends(get_state)):
    originals = Path(state.settings.data_dir) / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    data = body.text.encode()
    import hashlib
    chash = hashlib.sha256(data).hexdigest()
    existing = state.conn.execute("SELECT id FROM documents WHERE content_hash=?", (chash,)).fetchone()
    if existing:
        return {"id": existing[0], "status": "duplicate"}
    doc_id = _create_row(state, f"{body.title}.txt", body.title, "txt", len(data), chash)
    (originals / f"{doc_id}_{body.title}.txt").write_bytes(data)
    state.ingest.enqueue(doc_id)
    return {"id": doc_id, "status": "pending"}


@router.get("/documents", response_model=list[DocumentOut])
def list_docs(state=Depends(get_state)):
    return store.list_documents(state.conn)


class BulkDelete(BaseModel):
    ids: list[int]


@router.post("/documents/bulk-delete")
def bulk_delete(body: BulkDelete, state=Depends(get_state)):
    """Delete several documents in one call (Library multi-select). Reports the number
    actually removed, not just how many ids were requested."""
    deleted = 0
    for doc_id in body.ids:
        if store.document_exists(state.conn, doc_id):
            db.delete_document(state.conn, doc_id, state.vector_index)
            deleted += 1
    return {"deleted": deleted}


@router.get("/documents/{doc_id}", response_model=DocumentInfo)
def get_doc(doc_id: int, state=Depends(get_state)):
    doc = store.get_document(state.conn, doc_id)
    if doc is None:
        raise HTTPException(404, "not found")
    return doc


@router.get("/documents/{doc_id}/download")
def download_doc(doc_id: int, state=Depends(get_state)):
    filename = store.original_filename(state.conn, doc_id)
    if not filename:
        raise HTTPException(404, "not found")
    path = Path(state.settings.data_dir) / "originals" / f"{doc_id}_{filename}"
    if not path.exists():
        raise HTTPException(404, "original file not available")
    return FileResponse(str(path), filename=filename)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_doc(doc_id: int, state=Depends(get_state)):
    db.delete_document(state.conn, doc_id, state.vector_index)
    return None
