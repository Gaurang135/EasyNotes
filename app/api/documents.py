from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from app import db
from app.models import Status
from app.ingest import validation
from app.api.deps import get_state

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


@router.post("/documents", status_code=201)
def upload(background: BackgroundTasks, file: UploadFile = File(...), state=Depends(get_state)):
    originals = Path(state.settings.data_dir) / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    tmp = originals / f"_tmp_{file.filename}"
    tmp.write_bytes(file.file.read())
    validation.check_size(tmp, state.settings.max_upload_mb)
    ftype = validation.sniff_type(tmp, file.filename or "")
    if ftype not in state.parsers:
        tmp.unlink(missing_ok=True)
        raise HTTPException(415, f"unsupported file type: {ftype}")
    chash = validation.content_hash(tmp)
    existing = state.conn.execute("SELECT id FROM documents WHERE content_hash=?", (chash,)).fetchone()
    if existing:
        tmp.unlink(missing_ok=True)
        return {"id": existing[0], "status": "duplicate"}
    title = (file.filename or "untitled").rsplit(".", 1)[0]
    doc_id = _create_row(state, file.filename, title, ftype, tmp.stat().st_size, chash)
    tmp.rename(originals / f"{doc_id}_{file.filename}")
    background.add_task(state.pipeline.ingest, doc_id)
    return {"id": doc_id, "status": "pending"}


@router.post("/documents/text", status_code=201)
def paste(body: PasteText, background: BackgroundTasks, state=Depends(get_state)):
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
    background.add_task(state.pipeline.ingest, doc_id)
    return {"id": doc_id, "status": "pending"}


@router.get("/documents")
def list_docs(state=Depends(get_state)):
    rows = state.conn.execute(
        "SELECT id,title,file_type,status,error,uploaded_at FROM documents ORDER BY id DESC").fetchall()
    return [{"id": r[0], "title": r[1], "file_type": r[2], "status": r[3],
             "error": r[4], "uploaded_at": r[5]} for r in rows]


@router.get("/documents/{doc_id}")
def get_doc(doc_id: int, state=Depends(get_state)):
    r = state.conn.execute(
        "SELECT id,title,file_type,status,error,warnings FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r:
        raise HTTPException(404, "not found")
    return {"id": r[0], "title": r[1], "file_type": r[2], "status": r[3],
            "error": r[4], "warnings": json.loads(r[5] or "[]")}


@router.delete("/documents/{doc_id}", status_code=204)
def delete_doc(doc_id: int, state=Depends(get_state)):
    db.delete_document(state.conn, doc_id)
    return None
