from datetime import timezone
from hashlib import sha256
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from civiclens.db import Alert, Document, Item, ItemEvent, Meeting, Review, SourceDocument, Watch, utcnow
from civiclens.extraction import Observation
from civiclens.types import DECISIONS, Kind, State


def aware(date):
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date


def review(session: Session, code: str, detail: str, *, event=None, document=None) -> None:
    event_id = event.id if event else None
    doc_id = document.id if document else event.document_id if event else None
    fingerprint = sha256(f"{code}:{doc_id}:{event_id}:{detail}".encode()).hexdigest()
    if not session.scalar(select(Review.id).where(Review.fingerprint == fingerprint)):
        session.add(Review(fingerprint=fingerprint, code=code, detail=detail,
                           event_id=event_id, document_id=doc_id))


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if len(word) >= 3}


def similarity(title: str, previous: str) -> float:
    first, second = tokens(title), tokens(previous)
    return len(first & second) / max(1, len(first | second))


def resolve(session: Session, meeting: Meeting, observation: Observation) -> tuple[Item, bool]:
    candidates = session.scalars(select(Item).join(Meeting).where(
        Meeting.body == meeting.body, Item.official_id == observation.official_id
    )).all()
    same_meeting = []
    for item in candidates:
        previous = session.scalars(select(ItemEvent.title).where(
            ItemEvent.item_id == item.id, ItemEvent.meeting_key == meeting.key
        )).all()
        if previous and max(similarity(title, observation.title) for title in previous) >= 0.28:
            same_meeting.append(item)
    if len(same_meeting) == 1:
        return same_meeting[0], False
    cross_meeting = [item for item in candidates if
                     similarity(item.title, observation.title) >= 0.65]
    if not same_meeting and len(cross_meeting) == 1:
        return cross_meeting[0], False
    item = Item(official_id=observation.official_id, meeting_key=meeting.key,
                title=observation.title, topic=observation.topic, state=State.unknown)
    session.add(item)
    session.flush()
    return item, bool(candidates)


def matches(filters: dict, item: Item, meeting: Meeting) -> list[str]:
    reasons = []
    for key in ("q", "topic", "body", "ward", "location", "item_id"):
        expected = filters.get(key)
        if not expected:
            continue
        if key == "q":
            words = tokens(expected)
            matched = bool(words) and words <= tokens(f"{item.title} {item.official_id}")
        elif key == "ward":
            matched = expected in item.data.get("wards", [])
        elif key == "location":
            matched = any(expected.casefold() in address.casefold()
                          for address in item.data.get("locations", []))
        elif key == "item_id":
            matched = expected == item.id
        else:
            actual = item.topic if key == "topic" else meeting.body
            matched = expected.casefold() == actual.casefold()
        if not matched:
            return []
        reasons.append(f"{key.replace('q', 'keyword') if key == 'q' else key} matches {expected}")
    return reasons


def notify(session: Session, item: Item, event: ItemEvent, meeting: Meeting, transition: str) -> None:
    for watch in session.scalars(select(Watch).where(Watch.enabled.is_(True))):
        reasons = matches(watch.filters, item, meeting)
        if reasons and not session.scalar(select(Alert.id).where(
            Alert.watch_id == watch.id, Alert.item_id == item.id, Alert.transition == transition
        )):
            session.add(Alert(watch_id=watch.id, item_id=item.id, event_id=event.id,
                              transition=transition, message=" · ".join(reasons)))


def active_events(session: Session, item_id: str):
    newer = aliased(Document)
    newest = ~select(newer.id).where(newer.source_key == Document.source_key,
                                      newer.revision > Document.revision).exists()
    return session.execute(select(ItemEvent, Document, SourceDocument, Meeting)
                           .join(Document, Document.id == ItemEvent.document_id)
                           .join(SourceDocument, SourceDocument.key == Document.source_key)
                           .join(Meeting, Meeting.key == ItemEvent.meeting_key)
                           .where(ItemEvent.item_id == item_id, ItemEvent.suppressed.is_(False), newest)
                           .order_by(Meeting.starts_at, Document.processed_at, ItemEvent.sequence)).all()


def refresh_item(session: Session, item: Item, vectors=None, model: str | None = None) -> None:
    rows = active_events(session, item.id)
    if not rows:
        item.visible = False
        return
    item.visible = True
    # Titles come from proposals where available; minutes provide recorded action.
    proposals = [row for row in rows if row[2].kind in {Kind.agenda, Kind.notice}]
    descriptor = (proposals or rows)[-1]
    event, _, _, meeting = descriptor
    outcomes = {}
    for row in rows:
        record, document, source, sitting = row
        if source.kind == Kind.minutes and document.authoritative and record.state in DECISIONS:
            outcomes.setdefault(sitting.key, []).append(row)
    latest = next(reversed(outcomes.values()), [])
    if latest and aware(latest[-1][3].starts_at) < aware(meeting.starts_at):
        latest = []
    distinct = {record[0].state for record in latest}
    decision = latest[-1] if len(distinct) == 1 else None
    if len(distinct) > 1:
        for record in latest:
            review(session, "conflicting_evidence", "Different outcomes appear in active authoritative records.",
                   event=record[0])
    previous, previous_title = item.state, item.title
    item.title, item.topic, item.meeting_key = event.title, event.topic, meeting.key
    item.data = event.data
    item.search_text = " ".join([item.title, item.official_id, item.topic, meeting.body,
                                 meeting.location or ""])
    if decision:
        item.state = decision[0].state
    elif len(distinct) > 1:
        item.state = State.unknown
    elif any(row[0].state == State.discussed and row[3].key == meeting.key for row in rows):
        item.state = State.discussed
    elif proposals and aware(meeting.starts_at) > utcnow() and meeting.status != "cancelled":
        item.state = State.scheduled
    elif proposals and all(row[2].kind == Kind.notice for row in proposals):
        item.state = State.proposed
    else:
        item.state = State.unknown
    if vectors and event.title in vectors:
        item.embedding, item.embedding_model = vectors[event.title], model
    elif item.embedding_model and previous_title != event.title:
        item.embedding, item.embedding_model = None, None
    if decision and previous != item.state:
        action, _, _, sitting = decision
        notify(session, item, action, sitting, f"outcome:{sitting.key}:{item.state}")
    elif item.state == State.scheduled:
        notify(session, item, event, meeting, f"proposal:{meeting.key}")


def latest_document(session: Session, key: str) -> Document | None:
    return session.scalar(select(Document).where(Document.source_key == key)
                          .order_by(Document.revision.desc()).limit(1))
