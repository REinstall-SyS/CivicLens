"""initial civic records"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    if op.get_context().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('ingestion_runs',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('source_key', sa.String(length=180), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingestion_runs_source_key'), 'ingestion_runs', ['source_key'], unique=False)
    op.create_index(op.f('ix_ingestion_runs_started_at'), 'ingestion_runs', ['started_at'], unique=False)
    op.create_table('meetings',
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('title', sa.String(length=250), nullable=False),
        sa.Column('body', sa.String(length=140), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('location', sa.String(length=300), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_meetings_body'), 'meetings', ['body'], unique=False)
    op.create_index(op.f('ix_meetings_starts_at'), 'meetings', ['starts_at'], unique=False)
    op.create_table('subscribers',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('items',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('official_id', sa.String(length=32), nullable=False),
        sa.Column('meeting_key', sa.String(length=120), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('topic', sa.String(length=60), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('search_text', sa.Text(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('embedding', sa.JSON().with_variant(Vector(384), 'postgresql'), nullable=True),
        sa.Column('embedding_model', sa.Text(), nullable=True),
        sa.Column('visible', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['meeting_key'], ['meetings.key'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_items_meeting_key'), 'items', ['meeting_key'], unique=False)
    op.create_index(op.f('ix_items_official_id'), 'items', ['official_id'], unique=False)
    op.create_index(op.f('ix_items_state'), 'items', ['state'], unique=False)
    op.create_index(op.f('ix_items_topic'), 'items', ['topic'], unique=False)
    op.create_table('source_documents',
        sa.Column('key', sa.String(length=180), nullable=False),
        sa.Column('meeting_key', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('authoritative', sa.Boolean(), nullable=False),
        sa.Column('etag', sa.Text(), nullable=True),
        sa.Column('last_modified', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['meeting_key'], ['meetings.key'], ),
        sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_source_documents_meeting_key'), 'source_documents', ['meeting_key'], unique=False)
    op.create_table('watchlists',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('subscriber_id', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=140), nullable=False),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['subscriber_id'], ['subscribers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_watchlists_subscriber_id'), 'watchlists', ['subscriber_id'], unique=False)
    op.create_table('documents',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('source_key', sa.String(length=180), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('authoritative', sa.Boolean(), nullable=False),
        sa.Column('extraction_version', sa.String(length=80), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('bytes', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['source_key'], ['source_documents.key'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_key', 'revision')
    )
    op.create_index(op.f('ix_documents_sha256'), 'documents', ['sha256'], unique=False)
    op.create_index(op.f('ix_documents_source_key'), 'documents', ['source_key'], unique=False)
    op.create_table('item_events',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('item_id', sa.String(length=32), nullable=False),
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('meeting_key', sa.String(length=120), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('number', sa.String(length=32), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('topic', sa.String(length=60), nullable=False),
        sa.Column('state', sa.String(length=20), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('segment_keys', sa.JSON(), nullable=False),
        sa.Column('method', sa.String(length=40), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('suppressed', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
        sa.ForeignKeyConstraint(['meeting_key'], ['meetings.key'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'sequence')
    )
    op.create_index('ix_events_item_document', 'item_events', ['item_id', 'document_id'], unique=False)
    op.create_index(op.f('ix_item_events_document_id'), 'item_events', ['document_id'], unique=False)
    op.create_index(op.f('ix_item_events_item_id'), 'item_events', ['item_id'], unique=False)
    op.create_table('page_text',
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('method', sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.PrimaryKeyConstraint('document_id', 'number')
    )
    op.create_table('segments',
        sa.Column('document_id', sa.String(length=32), nullable=False),
        sa.Column('key', sa.String(length=32), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('start', sa.Integer(), nullable=False),
        sa.Column('end', sa.Integer(), nullable=False),
        sa.Column('quote', sa.Text(), nullable=False),
        sa.Column('method', sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.PrimaryKeyConstraint('document_id', 'key')
    )
    op.create_table('alerts',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('watch_id', sa.String(length=32), nullable=False),
        sa.Column('item_id', sa.String(length=32), nullable=False),
        sa.Column('event_id', sa.String(length=32), nullable=False),
        sa.Column('transition', sa.String(length=100), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['item_events.id'], ),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
        sa.ForeignKeyConstraint(['watch_id'], ['watchlists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('watch_id', 'item_id', 'transition')
    )
    op.create_index(op.f('ix_alerts_watch_id'), 'alerts', ['watch_id'], unique=False)
    op.create_table('reviews',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('event_id', sa.String(length=32), nullable=True),
        sa.Column('document_id', sa.String(length=32), nullable=True),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['item_events.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fingerprint')
    )
    op.create_table('review_audit',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('review_id', sa.String(length=32), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor', sa.String(length=80), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


    if op.get_context().dialect.name == "postgresql":
        op.execute("CREATE INDEX ix_items_search_english ON items USING gin "
                   "(to_tsvector('english'::regconfig, search_text))")
        op.execute("CREATE INDEX ix_items_embedding_cosine ON items USING hnsw "
                   "(embedding vector_cosine_ops)")


def downgrade():
    op.drop_table('review_audit')
    op.drop_table('reviews')
    op.drop_index(op.f('ix_alerts_watch_id'), table_name='alerts')
    op.drop_table('alerts')
    op.drop_table('segments')
    op.drop_table('page_text')
    op.drop_index(op.f('ix_item_events_item_id'), table_name='item_events')
    op.drop_index(op.f('ix_item_events_document_id'), table_name='item_events')
    op.drop_index('ix_events_item_document', table_name='item_events')
    op.drop_table('item_events')
    op.drop_index(op.f('ix_documents_source_key'), table_name='documents')
    op.drop_index(op.f('ix_documents_sha256'), table_name='documents')
    op.drop_table('documents')
    op.drop_index(op.f('ix_watchlists_subscriber_id'), table_name='watchlists')
    op.drop_table('watchlists')
    op.drop_index(op.f('ix_source_documents_meeting_key'), table_name='source_documents')
    op.drop_table('source_documents')
    op.drop_index(op.f('ix_items_topic'), table_name='items')
    op.drop_index(op.f('ix_items_state'), table_name='items')
    op.drop_index(op.f('ix_items_official_id'), table_name='items')
    op.drop_index(op.f('ix_items_meeting_key'), table_name='items')
    op.drop_table('items')
    op.drop_table('subscribers')
    op.drop_index(op.f('ix_meetings_starts_at'), table_name='meetings')
    op.drop_index(op.f('ix_meetings_body'), table_name='meetings')
    op.drop_table('meetings')
    op.drop_index(op.f('ix_ingestion_runs_started_at'), table_name='ingestion_runs')
    op.drop_index(op.f('ix_ingestion_runs_source_key'), table_name='ingestion_runs')
    op.drop_table('ingestion_runs')
