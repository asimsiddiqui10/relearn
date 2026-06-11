"""API request/response models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class SpaceCreate(BaseModel):
    name: str
    description: str | None = None


class SpaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    role: str | None = None
    created_at: datetime


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: str
    title: str
    status: str
    document_id: uuid.UUID | None
    created_at: datetime


class IngestStatus(BaseModel):
    resource_id: uuid.UUID
    status: str
    stage: str | None
    error: str | None


class StructureNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    parent_node_id: uuid.UUID | None
    depth: int
    heading_text: str | None
    node_type: str
    page_start: int | None
    page_end: int | None
    subtree_chunk_count: int


class ChatSessionCreate(BaseModel):
    title: str | None = None


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str | None
    visibility: str
    created_at: datetime


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: str
    content: str
    citations_json: dict | None
    created_at: datetime


class ChatSendRequest(BaseModel):
    message: str


class DocumentMeta(BaseModel):
    id: uuid.UUID
    doc_type: str
    status: str
    page_dimensions: dict[str, list[float]]
    pdf_url: str
