from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256
from time import perf_counter
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from civiclens.config import Settings, settings
from civiclens.db import (Document, IngestionRun, Item, ItemEvent, Meeting, PageText, Segment,
                          SourceDocument, engine, utcnow, write_session)
from civiclens.documents import DocumentLimitError, download_pdf, read_pdf, store_pdf
from civiclens.extraction import EXTRACTION_VERSION, extract
from civiclens.intelligence import assess, embeddings
from civiclens.reconcile import aware, latest_document, refresh_item, resolve, review
from civiclens.types import DocumentRef, Kind, MeetingRef, State

logger = logging.getLogger(__name__)


class SourceChanged(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    id: str
    sha256: str
    authoritative: bool
    version: str
    etag: str | None
    last_modified: str | None


def upsert_meeting(session: Session, reference: MeetingRef) -> Meeting:
    row = session.get(Meeting, reference.key)
    if row is None:
        row = Meeting(key=reference.key)
        session.add(row)
    row.title, row.body = reference.title, reference.body
    # Persist all meeting times in UTC, including the SQLite development mode.
    row.starts_at = aware(reference.starts_at).astimezone(timezone.utc)
    row.location, row.source_url, row.status = reference.location, str(reference.source_url), reference.status
    session.flush()
    return row


def register(reference: MeetingRef, documents: list[DocumentRef] | None = None, bind=None) -> None:
    with write_session(bind) as session:
        meeting = upsert_meeting(session, reference)
        for spec in documents or []:
            if not session.get(SourceDocument, spec.key):
                session.add(SourceDocument(key=spec.key, meeting_key=reference.key, kind=spec.kind,
                                           url=str(spec.url), published_at=spec.published_at,
                                           authoritative=spec.authoritative))
        for item in session.scalars(select(Item).where(Item.meeting_key == meeting.key)):
            refresh_item(session, item)


def ingest(reference: MeetingRef, spec: DocumentRef, *, client: httpx.Client | None = None,
           payload: bytes | None = None, bind=None, config: Settings | None = None) -> str:
    bind = bind if bind is not None else engine()
    config = config or settings()
    start = perf_counter()
    with write_session(bind) as session:
        run = IngestionRun(source_key=spec.key, status="running")
        session.add(run)
    try:
        try:
            result = process(reference, spec, client, payload, bind, config)
        except DocumentLimitError:
            if spec.kind != Kind.attachment:
                raise
            register(reference, [spec], bind)
            result = "skipped_size"
    except Exception as exc:
        with write_session(bind) as session:
            tracked = session.get(IngestionRun, run.id)
            tracked.status = "failed"
            response = getattr(exc, "response", None)
            lines = str(exc).splitlines()
            detail = lines[0][:260] if isinstance(exc, (ValueError, SourceChanged)) and lines else type(exc).__name__
            tracked.detail = f"HTTP {response.status_code}" if response is not None else detail
            tracked.duration_ms = round((perf_counter() - start) * 1000)
        logger.warning("ingestion_failed", extra={"document_key": spec.key, "error_type": type(exc).__name__})
        raise
    with write_session(bind) as session:
        tracked = session.get(IngestionRun, run.id)
        tracked.status = result
        if result == "skipped_size":
            tracked.detail = "Attachment exceeds the local archive size limit. Official link retained."
        tracked.duration_ms = round((perf_counter() - start) * 1000)
    logger.info("ingestion_finished", extra={"document_key": spec.key, "status": result,
                                             "duration_ms": tracked.duration_ms})
    return result


def process(reference, spec, client, payload, bind, config) -> str:
    with Session(bind) as session:
        source = session.get(SourceDocument, spec.key)
        prior = latest_document(session, spec.key)
        snapshot = None
        if source and source.meeting_key != reference.key:
            raise ValueError("Document key already belongs to a different meeting")
        if source and prior and source.url == str(spec.url):
            snapshot = Snapshot(prior.id, prior.sha256, prior.authoritative, prior.extraction_version,
                                source.etag, source.last_modified)
        expected_id = prior.id if prior else None
        if prior and prior.published_at and spec.published_at:
            if aware(spec.published_at) < aware(prior.published_at):
                return "unchanged"
        if payload is None and snapshot and not (snapshot.etag or snapshot.last_modified):
            if prior.processed_at and aware(prior.processed_at) > utcnow() - timedelta(hours=6):
                if snapshot.authoritative == spec.authoritative and snapshot.version == EXTRACTION_VERSION:
                    if spec.published_at is None or (prior.published_at and
                                                     aware(spec.published_at) == aware(prior.published_at)):
                        raw = config.data_dir / "raw" / prior.sha256[:2] / f"{prior.sha256}.pdf"
                        if raw.is_file():
                            return "unchanged"
    validators = {}
    etag = last_modified = None
    if payload is None:
        if client is None:
            raise ValueError("A public HTTP client or PDF payload is required")
        if snapshot and snapshot.authoritative == spec.authoritative and snapshot.version == EXTRACTION_VERSION:
            if snapshot.etag:
                validators["If-None-Match"] = snapshot.etag
            if snapshot.last_modified:
                validators["If-Modified-Since"] = snapshot.last_modified
        payload, headers = download_pdf(client, str(spec.url), config.max_pdf_bytes, validators)
        if payload is None:
            raw = config.data_dir / "raw" / snapshot.sha256[:2] / f"{snapshot.sha256}.pdf"
            if raw.is_file():
                return "unchanged"
            payload, headers = download_pdf(client, str(spec.url), config.max_pdf_bytes)
            if payload is None:
                raise ValueError("Unexpected conditional response to an unconditional request")
        etag, last_modified = headers.get("etag"), headers.get("last-modified")

    digest = sha256(payload).hexdigest()
    reuse = (snapshot is not None and digest == snapshot.sha256 and
             spec.authoritative == snapshot.authoritative and snapshot.version == EXTRACTION_VERSION)
    if reuse:
        store_pdf(config.data_dir, payload)
    else:
        pages, errors = ([], []) if spec.kind == Kind.attachment else read_pdf(payload, config)
        store_pdf(config.data_dir, payload)
        assertions = extract(pages, spec.kind, spec.authoritative)
        issues, tokens_used = assess(config, assertions) if spec.kind == Kind.minutes else ([], None)
        try:
            vectors = embeddings([item.title for item in assertions], config.embedding_model)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            logger.warning("embeddings_unavailable", extra={"error_type": type(exc).__name__})
            vectors = {}

    with write_session(bind) as session:
        meeting = upsert_meeting(session, reference)
        current = latest_document(session, spec.key)
        if (current.id if current else None) != expected_id:
            if (current and current.sha256 == digest and current.source_url == str(spec.url)
                    and current.authoritative == spec.authoritative and current.extraction_version == EXTRACTION_VERSION):
                return "unchanged"
            raise SourceChanged("The document changed while another run was processing it. Retry discovery.")
        source = session.get(SourceDocument, spec.key)
        if source is None:
            source = SourceDocument(key=spec.key, meeting_key=meeting.key, kind=spec.kind)
            session.add(source)
        if source.kind != spec.kind:
            raise ValueError("Document key already belongs to a different kind")
        if payload and client is None and reuse:
            return "unchanged"
        source.url, source.published_at, source.authoritative = str(spec.url), spec.published_at, spec.authoritative
        source.etag, source.last_modified = etag, last_modified
        if reuse:
            return "unchanged"
        session.flush()
        document = Document(source_key=spec.key, revision=current.revision + 1 if current else 1,
                            sha256=digest, bytes=len(payload), source_url=str(spec.url),
                            published_at=spec.published_at, authoritative=spec.authoritative,
                            extraction_version=EXTRACTION_VERSION)
        session.add(document)
        session.flush()
        impacted = set(session.scalars(select(ItemEvent.item_id).where(
            ItemEvent.document_id == current.id)).all()) if current else set()
        for page in pages:
            session.add(PageText(document_id=document.id, number=page.number, text=page.text, method=page.method))
        if errors:
            review(session, "ocr_failed", f"OCR yielded no reliable text on PDF pages {errors}.", document=document)
        for issue in issues:
            review(session, "advanced_extraction", issue, document=document)
        if spec.kind in {Kind.agenda, Kind.minutes, Kind.notice} and not assertions:
            review(session, "unsupported_layout", "No supported item headings were found.", document=document)
        if tokens_used is not None:
            logger.info("model_usage", extra={"document_key": spec.key, "total_tokens": tokens_used})
        spans = set()
        for sequence, assertion in enumerate(assertions):
            if not assertion.evidence:
                continue
            item, ambiguous = resolve(session, meeting, assertion)
            event = ItemEvent(item_id=item.id, document_id=document.id, meeting_key=meeting.key,
                              sequence=sequence, number=assertion.number, title=assertion.title,
                              topic=assertion.topic, state=assertion.state, data=assertion.data,
                              segment_keys=[span.key for span in assertion.evidence], method=assertion.method,
                              confidence=assertion.confidence)
            session.add(event)
            for span in assertion.evidence:
                if span.key not in spans:
                    spans.add(span.key)
                    session.add(Segment(document_id=document.id, key=span.key, page=span.page, start=span.start,
                                        end=span.end, quote=span.quote, method=span.method))
            session.flush()
            impacted.add(item.id)
            if ambiguous:
                review(session, "ambiguous_match", "Official identifier repeated without sufficient text agreement.",
                       event=event)
            if assertion.confidence < 0.85:
                review(session, "unverified_decision" if assertion.state == State.unknown else "low_confidence",
                       "Inspect the source text and outcome evidence.", event=event)
            if any(float(amount["value"]) >= 10_000_000 for amount in assertion.data.get("amounts", [])):
                review(session, "financial_amount", "Recorded amount exceeds the $10 million review threshold.",
                       event=event)
        for item_id in impacted:
            refresh_item(session, session.get(Item, item_id), vectors, config.embedding_model)
    return "revised" if current else "processed"
