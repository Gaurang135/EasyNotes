"""Pydantic response models — typed API contracts, so responses aren't hand-built dicts."""
from __future__ import annotations
from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: int
    title: str
    file_type: str
    status: str
    error: str | None = None
    uploaded_at: str
    size: int
    field_count: int
    table_count: int


class DocumentInfo(BaseModel):
    id: int
    title: str
    file_type: str
    status: str
    error: str | None = None
    warnings: list[str] = []


class Field(BaseModel):
    key: str
    value: str
    kind: str


class OverviewTable(BaseModel):
    id: int
    name: str
    row_count: int


class OverviewItem(BaseModel):
    id: int
    title: str
    file_type: str
    status: str
    error: str | None = None
    fields: list[Field]
    field_count: int
    table_count: int
    tables: list[OverviewTable]


class DetailTable(BaseModel):
    id: int
    name: str
    columns: list[dict]
    row_count: int


class DetailOut(BaseModel):
    id: int
    title: str
    file_type: str
    status: str
    error: str | None = None
    fields: list[Field]
    tables: list[DetailTable]
    text_preview: str
    chunk_count: int


class TableInfo(BaseModel):
    id: int
    document_id: int
    document_title: str
    name: str
    columns: list[dict]
    row_count: int
    file_type: str


class FieldRow(BaseModel):
    document_id: int
    document_title: str
    key: str
    value: str
    kind: str
