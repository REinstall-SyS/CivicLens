from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, create_engine, event, text)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from civiclens.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def identifier() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class Meeting(Base):
    __tablename__ = "meetings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    title: Mapped[str] = mapped_column(String(250))
    body: Mapped[str] = mapped_column(String(140), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    location: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))


class SourceDocument(Base):
    __tablename__ = "source_documents"
    key: Mapped[str] = mapped_column(String(180), primary_key=True)
    meeting_key: Mapped[str] = mapped_column(ForeignKey("meetings.key"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authoritative: Mapped[bool] = mapped_column(Boolean, default=False)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("source_key", "revision"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    source_key: Mapped[str] = mapped_column(ForeignKey("source_documents.key"), index=True)
    revision: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authoritative: Mapped[bool] = mapped_column(Boolean)
    extraction_version: Mapped[str] = mapped_column(String(80))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    bytes: Mapped[int]


class PageText(Base):
    __tablename__ = "page_text"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(12))


class Segment(Base):
    __tablename__ = "segments"
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    page: Mapped[int]
    start: Mapped[int]
    end: Mapped[int]
    quote: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(12))


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    official_id: Mapped[str] = mapped_column(String(32), index=True)
    meeting_key: Mapped[str] = mapped_column(ForeignKey("meetings.key"), index=True)
    title: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(60), index=True)
    state: Mapped[str] = mapped_column(String(20), index=True)
    search_text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSON().with_variant(Vector(384), "postgresql"))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)


class ItemEvent(Base):
    __tablename__ = "item_events"
    __table_args__ = (UniqueConstraint("document_id", "sequence"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    meeting_key: Mapped[str] = mapped_column(ForeignKey("meetings.key"))
    sequence: Mapped[int]
    number: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(60))
    state: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON)
    segment_keys: Mapped[list] = mapped_column(JSON)
    method: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    source_key: Mapped[str] = mapped_column(String(180), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    duration_ms: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(24))
    detail: Mapped[str | None] = mapped_column(Text)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("item_events.id"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    code: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Audit(Base):
    __tablename__ = "review_audit"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    changes: Mapped[dict] = mapped_column(JSON)


class Subscriber(Base):
    __tablename__ = "subscribers"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Watch(Base):
    __tablename__ = "watchlists"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    subscriber_id: Mapped[str] = mapped_column(ForeignKey("subscribers.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(140))
    filters: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("watch_id", "item_id", "transition"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("item_events.id"))
    transition: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_events_item_document", ItemEvent.item_id, ItemEvent.document_id)


@lru_cache
def engine_for(url: str):
    parsed = make_url(url)
    if parsed.drivername == "sqlite" and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 15000")
    return engine


def engine():
    return engine_for(settings().database_url)


@contextmanager
def write_session(bind=None):
    with Session(bind if bind is not None else engine(), expire_on_commit=False) as session, session.begin():
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(8265021)"))
        else:
            session.execute(text("BEGIN IMMEDIATE"))
        yield session
