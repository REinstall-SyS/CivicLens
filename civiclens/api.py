from contextlib import asynccontextmanager
from hashlib import sha256
import json
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from typing import Annotated, Literal

from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from civiclens.config import settings
from civiclens.db import (Alert, Audit, Document, IngestionRun, Item, ItemEvent, Meeting, PageText,
                          Review, Segment, SourceDocument, Subscriber, Watch, engine, utcnow, write_session)
from civiclens.extraction import Citation, claim_fields, normalize, topic_for
from civiclens.pipeline import ingest
from civiclens.queries import Filters, event_card, evidence, item_card, meeting_card, meeting_detail, search
from civiclens.reconcile import aware, matches, refresh_item
from civiclens.sources import PUBLIC_HOSTS
from civiclens.types import DECISIONS, DocumentRef, Kind, MeetingRef, State

COOKIE = "civiclens_watch"


def transaction():
    bind = engine()
    with Session(bind) as session:
        if bind.dialect.name == "postgresql":
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        else:
            session.execute(text("BEGIN"))
        yield session


Database = Annotated[Session, Depends(transaction)]


@asynccontextmanager
async def lifespan(_app):
    settings().data_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="CivicLens", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings().cors_origin], allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "Authorization"])


def visible_item(db, key):
    item = db.get(Item, key)
    if not item or not item.visible:
        raise HTTPException(404, "Item not found")
    return item


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/readyz")
def ready(db: Database):
    db.execute(select(Meeting.key).limit(1))
    return {"status": "ready"}


@app.get("/v1/home")
def home(db: Database):
    latest = db.scalars(select(Item).join(Meeting).where(Item.visible.is_(True), Item.state.in_(DECISIONS))
                        .order_by(desc(Meeting.starts_at), Item.official_id).limit(4)).all()
    upcoming = db.scalars(select(Meeting).where(Meeting.starts_at >= utcnow(), Meeting.status != "cancelled")
                          .order_by(Meeting.starts_at).limit(5)).all()
    recent = db.scalars(select(Item).join(Meeting).where(Item.visible.is_(True), Item.state.not_in(DECISIONS))
                        .order_by(desc(Meeting.starts_at), Item.official_id).limit(4)).all()
    latest_record = db.scalar(select(func.max(Meeting.starts_at)).select_from(Meeting)
                              .join(SourceDocument).join(Document))
    return {"decisions": [item_card(db, item) for item in latest],
            "proposals": [item_card(db, item) for item in recent],
            "upcoming": [meeting_card(meeting) for meeting in upcoming],
            "latest_record": aware(latest_record) if latest_record else None,
            "llm_configured": settings().llm_enabled,
            "embedding_configured": bool(settings().embedding_model)}


@app.get("/v1/items")
def items(filters: Annotated[Filters, Query()], db: Database):
    ids = search(db, filters, settings().embedding_model)
    return {"items": [item_card(db, db.get(Item, key)) for key in ids]}


@app.get("/v1/items/{key}")
def item(key: str, db: Database):
    return item_card(db, visible_item(db, key), detail=True)


@app.get("/v1/meetings")
def meetings(db: Database, upcoming: bool = False, limit: int = Query(35, ge=1, le=75)):
    statement = select(Meeting)
    if upcoming:
        statement = statement.where(Meeting.starts_at >= utcnow(), Meeting.status != "cancelled")
    return [meeting_card(row) for row in db.scalars(statement.order_by(
        Meeting.starts_at if upcoming else desc(Meeting.starts_at), Meeting.key).limit(limit))]


@app.get("/v1/meetings/{key}")
def meeting(key: str, db: Database):
    record = db.get(Meeting, key)
    if not record:
        raise HTTPException(404, "Meeting not found")
    return meeting_detail(db, record)


@app.get("/v1/documents/{key}/pdf")
def pdf(key: str, db: Database):
    document = db.get(Document, key)
    if not document:
        raise HTTPException(404, "Document not found")
    path = settings().data_dir / "raw" / document.sha256[:2] / f"{document.sha256}.pdf"
    if not path.is_file():
        raise HTTPException(404, "Archived PDF unavailable. Use the official source.")
    return FileResponse(path, media_type="application/pdf", headers={
        "Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff",
        "Cache-Control": "public, max-age=86400, immutable",
    })


@app.get("/v1/documents/{key}/pages/{page}")
def page_text(key: str, page: int, db: Database):
    record = db.get(PageText, (key, page))
    if not record:
        raise HTTPException(404, "Page not found")
    return {"page": record.number, "text": record.text, "method": record.method}


class WatchDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=140)
    q: str | None = Field(default=None, max_length=180)
    topic: str | None = Field(default=None, max_length=60)
    body: str | None = Field(default=None, max_length=140)
    ward: int | None = Field(default=None, ge=1, le=5)
    location: str | None = Field(default=None, max_length=180)
    item_id: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def require_filter(self):
        if not any(self.model_dump(exclude={"label"}).values()):
            raise ValueError("Enter a keyword, project, body, topic, ward or recorded location")
        return self


class WatchPreference(BaseModel):
    enabled: bool


def subscriber_key(token: str | None) -> str:
    return sha256((token or "").encode()).hexdigest()


def watch_row(watch: Watch) -> dict:
    return {"id": watch.id, "label": watch.label, "filters": watch.filters, "enabled": watch.enabled}


@app.get("/v1/watchlists")
def watches(db: Database, session: str | None = Cookie(None, alias=COOKIE)):
    key = subscriber_key(session)
    records = db.scalars(select(Watch).where(Watch.subscriber_id == key).order_by(Watch.created_at)).all()
    alerts = db.execute(select(Alert, Watch, ItemEvent, Document, SourceDocument, Meeting, Item)
                        .join(Watch, Watch.id == Alert.watch_id)
                        .join(ItemEvent, ItemEvent.id == Alert.event_id)
                        .join(Document, Document.id == ItemEvent.document_id)
                        .join(SourceDocument, SourceDocument.key == Document.source_key)
                        .join(Meeting, Meeting.key == ItemEvent.meeting_key)
                        .join(Item, Item.id == Alert.item_id).where(Watch.subscriber_id == key)
                        .order_by(Alert.created_at.desc()).limit(75)).all()
    pending = []
    if records:
        upcoming = db.execute(select(Item, Meeting).join(Meeting).where(
            Item.visible.is_(True), Item.state == State.scheduled, Meeting.starts_at >= utcnow()
        ).order_by(Meeting.starts_at)).all()
        for item, meeting in upcoming:
            labels = [watch.label for watch in records if watch.enabled and matches(watch.filters, item, meeting)]
            if labels:
                pending.append({"item": item_card(db, item), "watchlists": labels})
            if len(pending) == 20:
                break
    return {"watchlists": [watch_row(watch) for watch in records], "upcoming": pending,
            "alerts": [{"id": alert.id, "item_id": item.id, "title": event.title,
                        "watch": watch.label, "message": alert.message, "type": alert.transition,
                        "created_at": aware(alert.created_at), "meeting": meeting_card(meeting),
                        "source": evidence(db, event, document, source.kind)[-1]["source_url"]}
                       for alert, watch, event, document, source, meeting, item in alerts]}


@app.post("/v1/watchlists", status_code=201)
def create_watch(draft: WatchDraft, response: Response, session: str | None = Cookie(None, alias=COOKIE)):
    with write_session() as db:
        key = subscriber_key(session)
        if not db.get(Subscriber, key):
            session = token_urlsafe(32)
            key = subscriber_key(session)
            db.add(Subscriber(id=key))
            db.flush()
            response.set_cookie(COOKIE, session, max_age=31_536_000, httponly=True, samesite="strict",
                                secure=settings().secure_cookies)
        if db.scalar(select(func.count(Watch.id)).where(Watch.subscriber_id == key)) >= 25:
            raise HTTPException(409, "Watchlist limit reached")
        if draft.item_id:
            visible_item(db, draft.item_id)
        watch = Watch(subscriber_id=key, label=draft.label,
                      filters=draft.model_dump(exclude={"label"}, exclude_none=True))
        db.add(watch)
        db.flush()
        return watch_row(watch)


def own_watch(db, key, session):
    watch = db.get(Watch, key)
    if not watch or watch.subscriber_id != subscriber_key(session):
        raise HTTPException(404, "Watchlist not found")
    return watch


@app.patch("/v1/watchlists/{key}")
def preference(key: str, preference: WatchPreference, session: str | None = Cookie(None, alias=COOKIE)):
    with write_session() as db:
        watch = own_watch(db, key, session)
        watch.enabled = preference.enabled
        return watch_row(watch)


@app.delete("/v1/watchlists/{key}", status_code=204)
def unsubscribe(key: str, session: str | None = Cookie(None, alias=COOKIE)):
    with write_session() as db:
        db.delete(own_watch(db, key, session))


@app.delete("/v1/profile", status_code=204)
def remove_profile(response: Response, session: str | None = Cookie(None, alias=COOKIE)):
    with write_session() as db:
        subscriber = db.get(Subscriber, subscriber_key(session))
        if subscriber:
            db.delete(subscriber)
    response.delete_cookie(COOKIE, secure=settings().secure_cookies, httponly=True, samesite="strict")


def admin(authorization: str = Header("")) -> str:
    expected = settings().admin_token
    supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    if not expected or not supplied or not compare_digest(supplied.encode(), expected.get_secret_value().encode()):
        raise HTTPException(401, "Reviewer credentials required")
    return "local-reviewer"


Reviewer = Annotated[str, Depends(admin)]


@app.get("/v1/admin/evaluation")
def reference_evaluation(_actor: Reviewer):
    report = Path(__file__).resolve().parents[1] / "evaluation" / "results.json"
    if not report.is_file():
        report = Path.cwd() / "evaluation" / "results.json"
    if not report.is_file():
        raise HTTPException(404, "The reference evaluation is unavailable")
    return json.loads(report.read_text(encoding="utf-8"))


@app.get("/v1/admin/health")
def pipeline_health(db: Database, _actor: Reviewer):
    runs = db.scalars(select(IngestionRun).order_by(desc(IngestionRun.started_at)).limit(70)).all()
    queue = db.scalars(select(Review).order_by(Review.resolved_at.is_not(None), Review.created_at.desc())
                       .limit(70)).all()
    average = db.scalar(select(func.avg(IngestionRun.duration_ms)).where(
        IngestionRun.status.in_(["processed", "revised"])))
    output = []
    for review in queue:
        event = db.get(ItemEvent, review.event_id) if review.event_id else None
        document = db.get(Document, review.document_id) if review.document_id else None
        body = None
        if event and document:
            source = db.get(SourceDocument, document.source_key)
            body = event_card(db, (event, document, source, db.get(Meeting, event.meeting_key)))
        output.append({"id": review.id, "code": review.code, "detail": review.detail,
                       "resolved": bool(review.resolved_at), "event": body,
                       "document_url": document.source_url if document else None})
    return {"runs": [{"key": run.source_key, "status": run.status, "detail": run.detail,
                      "duration_ms": run.duration_ms, "started_at": aware(run.started_at)} for run in runs],
            "reviews": output, "mean_processing_ms": round(average) if average is not None else None,
            "item_count": db.scalar(select(func.count(Item.id)).where(Item.visible.is_(True)))}


class ReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["acknowledge", "reject", "correct"]
    reason: str = Field(min_length=8, max_length=1400)
    title: str | None = Field(default=None, min_length=8, max_length=2400)
    outcome: State | None = None
    page: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, min_length=8, max_length=1800)


@app.post("/v1/admin/reviews/{key}")
def apply_review(key: str, action: ReviewAction, actor: Reviewer):
    with write_session() as db:
        review = db.get(Review, key)
        if not review:
            raise HTTPException(404, "Review not found")
        if review.resolved_at:
            raise HTTPException(409, "Review already resolved")
        event = db.get(ItemEvent, review.event_id) if review.event_id else None
        changes = {}
        if action.action in {"correct", "reject"} and not event:
            raise HTTPException(422, "Select a review with an item observation")
        if action.action == "correct":
            page = db.get(PageText, (event.document_id, action.page)) if action.page else None
            if not page or not action.quote or action.quote not in page.text:
                raise HTTPException(422, "Provide a verbatim source quote and its PDF page")
            if not (action.title or action.outcome):
                raise HTTPException(422, "Provide a title or disposition correction")
            if action.title and normalize(action.title) not in normalize(action.quote):
                raise HTTPException(422, "The corrected wording must occur in the quote")
            document = db.get(Document, event.document_id)
            source = db.get(SourceDocument, document.source_key)
            if action.outcome in DECISIONS and not (document.authoritative and source.kind == Kind.minutes):
                raise HTTPException(422, "A confirmed disposition requires authoritative minutes")
            start = page.text.index(action.quote)
            quote = Citation(page.number, start, start + len(action.quote), action.quote, page.method)
            if not db.get(Segment, (event.document_id, quote.key)):
                db.add(Segment(document_id=event.document_id, key=quote.key, page=quote.page, start=quote.start,
                               end=quote.end, quote=quote.quote, method=quote.method))
            changes["before"] = {"title": event.title, "status": event.state, "data": event.data,
                                 "source_segments": event.segment_keys, "method": event.method}
            if action.title:
                event.title, event.topic = action.title, topic_for(action.title)
                event.data = {**event.data, **claim_fields(action.title)}
            if action.outcome:
                event.state = action.outcome
                event.data = {name: value for name, value in event.data.items()
                              if name not in {"vote", "motion", "yeas_as_recorded"}}
            event.segment_keys = list(dict.fromkeys([*event.segment_keys, quote.key]))
            event.method, event.confidence = "human-review", 1.0
            changes["after"] = {"title": event.title, "status": event.state, "source_segment": quote.key}
        if action.action == "reject":
            changes["before"] = {"suppressed": event.suppressed}
            event.suppressed = True
            changes["after"] = {"suppressed": True}
        if event:
            db.flush()
            refresh_item(db, db.get(Item, event.item_id))
        review.resolved_at = utcnow()
        db.add(Audit(review_id=key, actor=actor, action=action.action, reason=action.reason, changes=changes))
    return {"resolved": True}


@app.get("/v1/admin/reviews/{key}/audit")
def audit_review(key: str, db: Database, _actor: Reviewer):
    return [{"at": aware(entry.at), "actor": entry.actor, "action": entry.action,
             "reason": entry.reason, "changes": entry.changes}
            for entry in db.scalars(select(Audit).where(Audit.review_id == key).order_by(Audit.at))]


@app.post("/v1/admin/import")
def manual_import(_actor: Reviewer, meeting: Annotated[str, Form()], document: Annotated[str, Form()],
                  pdf_file: Annotated[UploadFile, File()]):
    try:
        meeting_ref = MeetingRef.model_validate_json(meeting)
        document_ref = DocumentRef.model_validate_json(document)
    except ValidationError as exc:
        raise HTTPException(422, "Meeting or document metadata is invalid") from exc
    if document_ref.url.scheme != "https" or document_ref.url.host not in PUBLIC_HOSTS:
        raise HTTPException(422, "Provide an official Hattiesburg PDF source URL")
    payload = pdf_file.file.read(settings().max_pdf_bytes + 1)
    try:
        return {"status": ingest(meeting_ref, document_ref, payload=payload)}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, "The PDF could not be imported. Check pipeline health.") from exc
