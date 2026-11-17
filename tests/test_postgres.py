from io import StringIO
import os

from alembic import command
from alembic.config import Config
from pgvector.sqlalchemy import Vector
import pytest
from sqlalchemy import cast, select, text
from sqlalchemy.orm import Session

from civiclens.config import settings
from civiclens.db import Item, engine_for, write_session
from civiclens.pipeline import ingest
from civiclens.queries import Filters, search
from civiclens.types import Kind
from test_pipeline import AGENDA, document, pdf, reference


def test_postgres_migrations_search_and_pgvector(monkeypatch, tmp_path):
    url = os.environ.get("CIVICLENS_PG_TEST_URL")
    if not url:
        pytest.skip("Set CIVICLENS_PG_TEST_URL to a disposable PostgreSQL database with pgvector installed")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        with Session(engine_for(url)) as session:
            assert session.scalar(text("SELECT extname FROM pg_extension WHERE extname='vector'")) == "vector"
        meeting = reference()
        ingest(meeting, document(meeting, Kind.agenda), payload=pdf(AGENDA))
        with write_session(engine_for(url)) as session:
            row = session.scalar(select(Item).where(Item.official_id == "2026-012"))
            row.embedding, row.embedding_model = [1.0] + [0.0] * 383, "test-model"
            key = row.id
        with Session(engine_for(url)) as session:
            assert search(session, Filters(q="bridge repairs", ward=2, location="Main Street")) == [key]
            distance = session.scalar(select(cast(Item.embedding, Vector(384)).cosine_distance([1.0] + [0.0] * 383))
                                      .where(Item.id == key))
            assert distance == 0
            monkeypatch.setattr("civiclens.queries.embeddings",
                                lambda terms, model: {terms[0]: [1.0] + [0.0] * 383})
            assert search(session, Filters(q="infrastructure"), "test-model") == [key]
    finally:
        settings.cache_clear()

def test_offline_postgres_migration_creates_vector_before_tables(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://civic:test@localhost/civic")
    settings.cache_clear()
    try:
        output = StringIO()
        command.upgrade(Config("alembic.ini", output_buffer=output), "head", sql=True)
        sql = output.getvalue().lower()
        assert sql.index("create extension if not exists vector") < sql.index("embedding vector(384)")
        assert "using gin" in sql and "using hnsw" in sql
    finally:
        settings.cache_clear()
