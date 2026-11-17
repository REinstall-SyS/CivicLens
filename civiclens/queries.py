import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pgvector.sqlalchemy import Vector
from sqlalchemy import String, cast, desc, exists, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from civiclens.extraction import CARRIED, TALLY, normalize

from civiclens.db import Document, Item, ItemEvent, Meeting, Segment, SourceDocument
from civiclens.intelligence import embeddings
from civiclens.reconcile import active_events, aware
from civiclens.types import DECISIONS, LOCAL, Kind, State

FTS = "to_tsvector('english'::regconfig, search_text)"
ENGLISH = literal_column("'english'::regconfig")
STOP = set("a an and are at be for from in is it of on or the to was were what when where which with"
           " recently upcoming projects city hattiesburg".split())


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=180)
    topic: str | None = Field(default=None, max_length=60)
    body: str | None = Field(default=None, max_length=140)
    state: State | None = None
    kind: Literal["proposal", "decision"] | None = None
    ward: int | None = Field(default=None, ge=1, le=5)
    location: str | None = Field(default=None, max_length=180)
    start: date | None = None
    end: date | None = None
    limit: int = Field(default=24, ge=1, le=60)

    @model_validator(mode="after")
    def dates_in_order(self):
        if self.start and self.end and self.end < self.start:
            raise ValueError("End date precedes start date")
        return self


def date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, LOCAL).astimezone(timezone.utc)


def terms_for(query: str) -> list[str]:
    key = re.fullmatch(r"20\d{2}-\d{3,5}", query.strip())
    if key:
        return [key[0]]
    return list(dict.fromkeys(word for word in re.findall(r"[a-z0-9]+", query.lower())
                              if word not in STOP))[:18]


def search(session, filters: Filters, embedding_model: str | None = None):
    conditions = [Item.visible.is_(True)]
    dialect = session.get_bind().dialect.name
    for column, value in [(Item.topic, filters.topic), (Meeting.body, filters.body), (Item.state, filters.state)]:
        if value:
            conditions.append(column == value)
    if filters.kind == "proposal":
        conditions.append(Item.state.not_in(DECISIONS))
    elif filters.kind == "decision":
        conditions.append(Item.state.in_(DECISIONS))
    if filters.ward:
        if dialect == "postgresql":
            conditions.append(cast(Item.data, JSONB)["wards"].contains([filters.ward]))
        else:
            table = func.json_each(Item.data, "$.wards").table_valued("value").alias("ward")
            conditions.append(exists(select(1).select_from(table).where(table.c.value == filters.ward)))
    if filters.location:
        if dialect == "postgresql":
            locations = func.jsonb_array_elements_text(cast(Item.data, JSONB)["locations"]).column_valued("address")
        else:
            table = func.json_each(Item.data, "$.locations").table_valued("value").alias("addresses")
            locations = table.c.value
        conditions.append(exists(select(1).where(cast(locations, String).icontains(filters.location, autoescape=True))))
    if filters.start:
        conditions.append(Meeting.starts_at >= date_start(filters.start))
    if filters.end:
        conditions.append(Meeting.starts_at < date_start(filters.end + timedelta(days=1)))
    base = select(Item.id).join(Meeting, Meeting.key == Item.meeting_key).where(*conditions)
    recent = (desc(Meeting.starts_at), Item.id)
    if not filters.q:
        return session.scalars(base.order_by(*recent).limit(filters.limit)).all()

    terms = terms_for(filters.q)
    if not terms:
        return []
    id_query = re.fullmatch(r"20\d{2}-\d{3,5}", filters.q)
    if id_query:
        return session.scalars(base.where(Item.official_id == filters.q).order_by(*recent).limit(filters.limit)).all()
    if dialect == "postgresql":
        vector = func.to_tsvector(ENGLISH, Item.search_text)
        query = func.to_tsquery(ENGLISH, " | ".join(terms))
        phrase = func.plainto_tsquery(ENGLISH, " ".join(terms))
        rank = func.ts_rank_cd(vector, query) + 2 * func.ts_rank_cd(vector, phrase)
        lexical = session.scalars(base.where(vector.op("@@")(query)).order_by(rank.desc(), *recent)
                                  .limit(120)).all()
    else:
        from sqlalchemy import case
        matches = [Item.search_text.icontains(term, autoescape=True) for term in terms]
        points = sum(case((match, 1), else_=0) for match in matches)
        lexical = session.scalars(base.where(or_(*matches)).order_by(points.desc(), *recent).limit(120)).all()
    if dialect != "postgresql" or not embedding_model:
        return lexical[:filters.limit]
    try:
        query_vector = embeddings([filters.q], embedding_model)[filters.q]
    except (ImportError, OSError, RuntimeError, ValueError):
        return lexical[:filters.limit]
    distance = cast(Item.embedding, Vector(384)).cosine_distance(query_vector)
    semantic = session.scalars(base.where(Item.embedding_model == embedding_model,
                                         Item.embedding.is_not(None), distance < 0.67)
                               .order_by(distance, Item.id).limit(120)).all()
    ranks = {}
    for weight, ids in [(1.0, lexical), (0.75, semantic)]:
        for index, item in enumerate(ids, 1):
            ranks[item] = ranks.get(item, 0.0) + weight / (40 + index)
    return sorted(ranks, key=lambda key: -ranks[key])[:filters.limit]


def meeting_card(meeting: Meeting) -> dict:
    return {"key": meeting.key, "title": meeting.title, "body": meeting.body,
            "starts_at": aware(meeting.starts_at), "location": meeting.location,
            "source_url": meeting.source_url, "status": meeting.status}


def evidence(session, event: ItemEvent, document: Document, kind: str) -> list[dict]:
    segments = {segment.key: segment for segment in session.scalars(select(Segment).where(
        Segment.document_id == document.id, Segment.key.in_(event.segment_keys)
    ))}
    return [
        {"segment_id": key, "document_id": document.id, "page": span.page, "start": span.start,
         "end": span.end, "quote": span.quote, "method": span.method, "kind": kind,
         "source_url": f"{document.source_url}#page={span.page}", "revision": document.revision}
        for key in event.segment_keys if (span := segments.get(key))
    ]


def event_card(session, row) -> dict:
    event, document, source, meeting = row
    return {"id": event.id, "title": event.title, "number": event.number, "status": event.state,
            "kind": source.kind, "authoritative": document.authoritative, "revision": document.revision,
            "published_at": aware(document.published_at) if document.published_at else None,
            "recorded_at": aware(document.processed_at), "meeting": meeting_card(meeting),
            "method": event.method, "confidence": event.confidence,
            "extraction_version": document.extraction_version, "suppressed": event.suppressed,
            "details": event.data, "evidence": evidence(session, event, document, source.kind)}


def item_card(session, item: Item, *, detail: bool = False) -> dict:
    active = active_events(session, item.id)
    proof = [row for row in active if row[0].state == item.state and row[1].authoritative
             and row[2].kind == Kind.minutes] if item.state in DECISIONS else []
    proposal = [row for row in active if row[2].kind in {Kind.agenda, Kind.notice}]
    selected = (proof or proposal or active)[-1]
    refs = evidence(session, selected[0], selected[1], selected[2].kind)
    source = refs[0] if refs else None
    if proof:
        source = next((ref for ref in refs if CARRIED.search(normalize(ref["quote"]))), source)
        source = next((ref for ref in refs if TALLY.search(normalize(ref["quote"]))), source)
    payload = {"id": item.id, "official_id": item.official_id, "title": item.title, "topic": item.topic,
               "status": item.state, "verified": bool(proof), "details": item.data,
               "source": source,
               "meeting": meeting_card(session.get(Meeting, item.meeting_key))}
    if detail:
        rows = session.execute(select(ItemEvent, Document, SourceDocument, Meeting)
                               .join(Document, Document.id == ItemEvent.document_id)
                               .join(SourceDocument, SourceDocument.key == Document.source_key)
                               .join(Meeting, Meeting.key == ItemEvent.meeting_key)
                               .where(ItemEvent.item_id == item.id)
                               .order_by(Meeting.starts_at, SourceDocument.kind, Document.revision,
                                         ItemEvent.sequence)).all()
        current = {row[0].id for row in active}
        payload["timeline"] = [{**event_card(session, row), "current": row[0].id in current} for row in rows]
    return payload


def meeting_detail(session, meeting: Meeting) -> dict:
    items = session.scalars(select(Item).join(ItemEvent, ItemEvent.item_id == Item.id).where(
        Item.visible.is_(True), ItemEvent.meeting_key == meeting.key
    ).distinct().order_by(Item.official_id)).all()
    documents = session.execute(select(Document, SourceDocument).select_from(SourceDocument).outerjoin(Document)
                                .where(SourceDocument.meeting_key == meeting.key)
                                .order_by(SourceDocument.kind, Document.revision.desc())).all()
    return {**meeting_card(meeting), "items": [item_card(session, item) for item in items],
            "documents": [{"id": doc.id if doc else None, "kind": source.kind, "url": doc.source_url if doc else source.url,
                           "revision": doc.revision if doc else None, "sha256": doc.sha256 if doc else None,
                           "published_at": aware(date) if (date := doc.published_at if doc else source.published_at) else None,
                           "authoritative": doc.authoritative if doc else False} for doc, source in documents]}
