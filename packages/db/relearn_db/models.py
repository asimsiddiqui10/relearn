"""Relearn Postgres schema — one schema, hard FKs (spec/02).

Write ownership is a convention (backend: identity/workspace/chat-metadata;
AI service: corpus/runs), but every constraint is enforced here by the DB.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024  # BGE-M3


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


# ---------------------------------------------------------------------------
# Identity & workspace (written by backend)
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    # Cognito `sub` in prod; locally-generated id in dev auth.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    # dev-auth only; null when the user comes from an external issuer
    password_hash: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = created_at_col()


class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)  # space-level agent guidance
    memory: Mapped[str | None] = mapped_column(Text)  # comments/remarks/tasks/changelog
    settings_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()


class SpaceMember(Base):
    __tablename__ = "space_members"
    __table_args__ = (
        UniqueConstraint("space_id", "user_id"),
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="space_members_role"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default="member")
    invited_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime] = created_at_col()


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("type IN ('document', 'link', 'note', 'plan')", name="resources_type"),
        CheckConstraint(
            "status IN ('pending', 'ingesting', 'ready', 'failed')", name="resources_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    visibility: Mapped[str] = mapped_column(String, nullable=False, server_default="space")
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = created_at_col()


# ---------------------------------------------------------------------------
# Document corpus (written by AI service)
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # re-upload within a space short-circuits to the existing document
        UniqueConstraint("space_id", "checksum"),
        CheckConstraint(
            "doc_type IN ('textbook', 'notes', 'question_paper', 'slides')",
            name="documents_doc_type",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)  # S3 key pdfs/{sha256}.pdf
    checksum: Mapped[str] = mapped_column(String, nullable=False)  # sha256
    doc_type: Mapped[str] = mapped_column(String, nullable=False, server_default="textbook")
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    summary: Mapped[str | None] = mapped_column(Text)
    summary_token_count: Mapped[int | None] = mapped_column(Integer)
    # includes page_dimensions for the visualizer
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()


class StructureNode(Base):
    __tablename__ = "structure_nodes"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("structure_nodes.id", ondelete="CASCADE")
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_level: Mapped[int | None] = mapped_column(Integer)
    heading_text: Mapped[str | None] = mapped_column(Text)
    node_type: Mapped[str] = mapped_column(String, nullable=False, server_default="section")
    structure_path: Mapped[str | None] = mapped_column(String)  # e.g. "1/2.3/4"
    heading_breadcrumb: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    subtree_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    subtree_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    summary: Mapped[str | None] = mapped_column(Text)
    normalization_flags: Mapped[dict | None] = mapped_column(JSONB)
    marker_block_id: Mapped[str | None] = mapped_column(String)


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        # instant figure-reference lookup
        Index("ix_images_document_figure_ref", "document_id", "figure_ref_norm"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    structure_node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("structure_nodes.id", ondelete="SET NULL")
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSONB)
    file_path: Mapped[str | None] = mapped_column(String)
    caption: Mapped[str | None] = mapped_column(Text)
    caption_embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM))
    figure_ref_norm: Mapped[str | None] = mapped_column(String)  # e.g. "figure_2_1"


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint(
            "chunk_type IN ('text', 'caption', 'question', 'equation', 'table')",
            name="chunks_chunk_type",
        ),
        Index("ix_chunks_document_page", "document_id", "page_number"),
        Index("ix_chunks_structure_node", "structure_node_id"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    structure_node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("structure_nodes.id", ondelete="CASCADE")
    )
    chunk_type: Mapped[str] = mapped_column(String, nullable=False, server_default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_html: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSONB)  # raw Marker coordinate space
    polygon: Mapped[list | None] = mapped_column(JSONB)  # raw Marker coordinate space
    token_count: Mapped[int | None] = mapped_column(Integer)
    structure_path: Mapped[str | None] = mapped_column(String)
    heading_breadcrumb: Mapped[str | None] = mapped_column(Text)
    attached_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL")
    )
    marker_block_id: Mapped[str | None] = mapped_column(String)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(content, ''))", persisted=True),
    )


class MarkerIngestRun(Base):
    """Raw + normalized Marker payloads — offline reprocessing without re-parsing."""

    __tablename__ = "marker_ingest_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    normalized_tree: Mapped[dict | None] = mapped_column(JSONB)
    marker_version: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = created_at_col()


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ingest_jobs_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="queued")
    stage: Mapped[str | None] = mapped_column(String)  # parse/normalize/map/embed/gate/...
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )


# ---------------------------------------------------------------------------
# Questions module (tables exist day 1; populated Phase 3+)
# ---------------------------------------------------------------------------


class SyllabusTopic(Base):
    __tablename__ = "syllabus_topics"

    id: Mapped[uuid.UUID] = uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str | None] = mapped_column(String)
    parent_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("syllabus_topics.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    ordering: Mapped[int | None] = mapped_column(Integer)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "provenance IN ('ingested', 'generated')", name="questions_provenance"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    # nullable — generated questions have no source document
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_html: Mapped[str | None] = mapped_column(Text)
    options_json: Mapped[dict | None] = mapped_column(JSONB)
    answer: Mapped[str | None] = mapped_column(Text)
    solution: Mapped[str | None] = mapped_column(Text)
    marks: Mapped[int | None] = mapped_column(Integer)
    difficulty: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(String)
    exam_name: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSONB)
    question_number: Mapped[int | None] = mapped_column(Integer)
    has_diagram: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM))
    provenance: Mapped[str] = mapped_column(String, nullable=False, server_default="ingested")
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at_col()


class QuestionTopic(Base):
    __tablename__ = "question_topics"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("syllabus_topics.id", ondelete="CASCADE"), primary_key=True
    )


# ---------------------------------------------------------------------------
# Chat & agent
# ---------------------------------------------------------------------------


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("visibility IN ('private', 'space')", name="chat_sessions_visibility"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String)
    visibility: Mapped[str] = mapped_column(String, nullable=False, server_default="private")
    # rolling compaction of older turns, incl. key [E#]→chunk_id mappings (spec/03)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_col()


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('interactive', 'background')", name="agent_runs_mode"),
        CheckConstraint(
            "status IN ('queued', 'running', 'suspended', 'completed', 'failed')",
            name="agent_runs_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[str] = mapped_column(String, nullable=False, server_default="interactive")
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflows.id"))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="queued")
    # messages + evidence-registry snapshot for suspend/resume + background checkpoints
    state_json: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class AgentRunEvent(Base):
    """Append-only trace of every SSE event — reconnect-replay, debugging, analytics."""

    __tablename__ = "agent_run_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_col()


class EvidenceLog(Base):
    __tablename__ = "evidence_log"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    eid: Mapped[str] = mapped_column(String, primary_key=True)  # "E1", "E2", ...
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSONB)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "signal IN ('helpful', 'not_helpful', 'flag_citation')", name="feedback_signal"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"))
    signal: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


# ---------------------------------------------------------------------------
# Workflows & background runs (Phase 4+ / spec 10 — schema exists day 1)
# ---------------------------------------------------------------------------


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    space_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE")  # nullable = personal
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    prompt_md: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at_col()


class WorkflowShare(Base):
    __tablename__ = "workflow_shares"
    __table_args__ = (
        CheckConstraint("access IN ('read', 'write')", name="workflow_shares_access"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    email: Mapped[str | None] = mapped_column(String)  # invite-by-email before signup
    access: Mapped[str] = mapped_column(String, nullable=False, server_default="read")


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("type IN ('notes', 'report')", name="artifacts_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content_md: Mapped[str | None] = mapped_column(Text)
    citations_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
    created_at: Mapped[datetime] = created_at_col()


class RunTask(Base):
    __tablename__ = "run_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done', 'failed')", name="run_tasks_status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="open")


class QuestionSourceMapping(Base):
    __tablename__ = "question_source_mappings"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('exact', 'conceptual', 'partial', 'unsupported')",
            name="qsm_classification",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    classification: Mapped[str] = mapped_column(String, nullable=False)
    evidence_chunk_ids: Mapped[list | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
