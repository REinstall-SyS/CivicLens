from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from civiclens.config import Settings
from civiclens.db import (Alert, Base, Document, IngestionRun, Item, Meeting, PageText, Review,
                          Subscriber, Watch, engine_for, write_session)
from civiclens.documents import Page, read_pdf
from civiclens.extraction import extract
from civiclens.intelligence import assess
from civiclens.pipeline import ingest
from civiclens.queries import Filters, item_card, meeting_detail, search
from civiclens.sources import HattiesburgCivicClerk, legistar_january_2019
from civiclens.types import DocumentRef, Kind, MeetingRef, State

TITLE = "Approve repairs to the bridge at 104 Main Street, Ward 2, for $25,001.50."
AGENDA = "1. 2026-012 " + TITLE
MOTION = ("A MOTION was made by Council Member Smith to {verb} the bridge repairs.\n"
          "The motion carried with the following vote:\nYeas: 5 - Council members\nNays: 0")


def pdf(text, *, scanned=False):
    with pymupdf.open() as doc:
        page = doc.new_page()
        result = page.insert_textbox((45, 45, 560, 770), text, fontsize=12)
        assert result >= 0
        if scanned:
            pixels = page.get_pixmap(dpi=140)
            with pymupdf.open() as scan:
                scan.new_page().insert_image(page.rect, pixmap=pixels)
                return scan.tobytes()
        return doc.tobytes()


@pytest.fixture
def work(tmp_path):
    config = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'test.db'}")
    db = engine_for(config.database_url)
    Base.metadata.create_all(db)
    yield db, config
    db.dispose()


def reference(key="test:1", days=-1):
    return MeetingRef(key=key, body="City Council", title="Council meeting",
                      starts_at=datetime.now(timezone.utc) + timedelta(days=days),
                      source_url="https://hattiesburgms.portal.civicclerk.com/event/1/files")


def document(meeting, kind, suffix=""):
    return DocumentRef(key=f"{meeting.key}:{kind}{suffix}", kind=kind, authoritative=kind == Kind.minutes,
                       url=f"https://hattiesburgms.api.civicclerk.com/{kind}{suffix}.pdf")


def put(work, meeting, kind, text, suffix=""):
    db, config = work
    return ingest(meeting, document(meeting, kind, suffix), payload=pdf(text), bind=db, config=config)


def test_duplicate_discovery_and_unchanged_document(work):
    db, config = work
    meeting = reference()
    spec = document(meeting, Kind.agenda)
    payload = pdf(AGENDA)
    requests = []

    def http(request):
        requests.append(request)
        if request.headers.get("If-None-Match") == '"revision-a"':
            return httpx.Response(304)
        return httpx.Response(200, content=payload, headers={"ETag": '"revision-a"'})

    with httpx.Client(transport=httpx.MockTransport(http)) as client:
        assert ingest(meeting, spec, client=client, bind=db, config=config) == "processed"
        assert ingest(meeting, spec, client=client, bind=db, config=config) == "unchanged"
    with Session(db) as session:
        assert len(session.scalars(select(Document)).all()) == 1
        assert len(session.scalars(select(Meeting)).all()) == 1
    assert len(requests) == 2


def test_revision_and_missing_minutes(work):
    meeting = reference()
    assert put(work, meeting, Kind.agenda, AGENDA) == "processed"
    assert put(work, meeting, Kind.agenda, AGENDA.replace("25,001.50", "27,001.50")) == "revised"
    with Session(work[0]) as session:
        item = session.scalars(select(Item)).one()
        card = item_card(session, item, detail=True)
        assert card["status"] == State.unknown
        assert not card["verified"]
        assert card["details"]["amounts"] == [{"value": "27001.50", "currency": "USD"}]
        assert [row["current"] for row in card["timeline"]] == [False, True]


@pytest.mark.parametrize(("verb", "state"), [("approve", State.approved), ("table", State.tabled),
                                              ("deny", State.rejected)])
def test_explicit_authoritative_outcomes_and_citation(work, verb, state):
    meeting = reference()
    put(work, meeting, Kind.agenda, AGENDA)
    put(work, meeting, Kind.minutes, AGENDA + "\n" + MOTION.format(verb=verb))
    with Session(work[0]) as db:
        card = item_card(db, db.scalars(select(Item)).one(), detail=True)
        assert card["verified"] and card["status"] == state
        assert card["source"]["kind"] == "minutes"
        for entry in card["timeline"]:
            for segment in entry["evidence"]:
                text = db.get(PageText, (segment["document_id"], segment["page"]))
                assert text.text[segment["start"]:segment["end"]] == segment["quote"]
                assert segment["source_url"].endswith(f"#page={segment['page']}")


def test_draft_and_unsigned_minutes_do_not_verify_outcomes(work):
    db, config = work
    meeting = reference()
    put(work, meeting, Kind.agenda, AGENDA)
    spec = document(meeting, Kind.minutes).model_copy(update={"authoritative": False})
    ingest(meeting, spec, payload=pdf(AGENDA + "\n" + MOTION.format(verb="approve")), bind=db, config=config)
    with Session(db) as session:
        assert session.scalars(select(Item)).one().state == State.unknown


def test_similar_titles_and_cross_meeting_id_consistency(work):
    first, next_meeting = reference(), reference("test:2")
    put(work, first, Kind.agenda, AGENDA)
    put(work, first, Kind.minutes, AGENDA.replace("2026-012", "2026-013") + "\n" + MOTION.format(verb="approve"))
    put(work, next_meeting, Kind.minutes, AGENDA + "\n" + MOTION.format(verb="table"))
    with Session(work[0]) as session:
        items = {item.official_id: item for item in session.scalars(select(Item))}
        assert len(items) == 2
        assert items["2026-012"].state == State.tabled
        assert items["2026-013"].state == State.approved


def test_conflicting_evidence_is_unverified(work):
    meeting = reference()
    put(work, meeting, Kind.agenda, AGENDA)
    put(work, meeting, Kind.minutes, AGENDA + "\n" + MOTION.format(verb="approve"))
    put(work, meeting, Kind.minutes, AGENDA + "\n" + MOTION.format(verb="deny"), "-second-record")
    with Session(work[0]) as db:
        assert db.scalars(select(Item)).one().state == State.unknown
        assert db.scalars(select(Review).where(Review.code == "conflicting_evidence")).first()


def test_watchlist_deduplicates_and_honors_pause(work):
    db, config = work
    upcoming = reference(days=14)
    with write_session(db) as session:
        session.add(Subscriber(id="test-subscriber"))
        session.flush()
        session.add(Watch(subscriber_id="test-subscriber", label="Bridge", filters={"q": "bridge"}))
    put(work, upcoming, Kind.agenda, AGENDA)
    put(work, upcoming, Kind.agenda, AGENDA.replace("25,001", "26,001"))
    past = upcoming.model_copy(update={"starts_at": datetime.now(timezone.utc) - timedelta(days=1)})
    payload = pdf(AGENDA + "\n" + MOTION.format(verb="approve"))
    for _ in range(2):
        ingest(past, document(past, Kind.minutes), payload=payload, config=config, bind=db)
    with write_session(db) as session:
        assert len(session.scalars(select(Alert)).all()) == 2
        session.scalars(select(Watch)).one().enabled = False
    put(work, reference("test:2", days=30), Kind.agenda, AGENDA.replace("2026-012", "2026-015"))
    with Session(db) as session:
        assert len(session.scalars(select(Alert)).all()) == 2


def test_search_filters_and_location(work):
    meeting = reference()
    put(work, meeting, Kind.agenda, AGENDA + "\n2. 2026-037 Improve municipal recycling services.")
    with Session(work[0]) as session:
        keyword = search(session, Filters(q="bridge repairs", ward=2, location="Main Street"))
        assert len(keyword) == 1
        assert session.get(Item, keyword[0]).official_id == "2026-012"
        assert search(session, Filters(q="bridge", kind="decision")) == []
        assert search(session, Filters(q="bridge", location="Broadway")) == []


def test_retry_after_failure_preserves_prior_revision(work):
    db, config = work
    meeting = reference()
    spec = document(meeting, Kind.agenda)
    response = httpx.MockTransport(lambda request: httpx.Response(503))
    with httpx.Client(transport=response) as client, pytest.raises(httpx.HTTPStatusError):
        ingest(meeting, spec, client=client, config=config, bind=db)
    assert put(work, meeting, Kind.agenda, AGENDA) == "processed"
    with Session(db) as session:
        assert [row.status for row in session.scalars(select(IngestionRun).order_by(IngestionRun.started_at))] == [
            "failed", "processed"]


def test_scanned_pdf_ocr(work, monkeypatch):
    import os
    from shutil import which

    config = work[1]
    tessdata = os.environ.get("TESSDATA_PREFIX")
    if not tessdata and not which("tesseract"):
        pytest.skip("Provide an English TESSDATA_PREFIX or installed Tesseract")
    config.tessdata = tessdata
    pages, failures = read_pdf(pdf(AGENDA, scanned=True), config)
    assert not failures
    assert pages[0].method == "ocr"
    assert "bridge" in pages[0].text.lower()


def test_model_rejects_unsupported_tally(monkeypatch):
    record = extract([Page(1, AGENDA + "\n" + MOTION.format(verb="approve"))], Kind.minutes, True)[0]
    span = record.evidence[-1]
    from json import dumps
    candidate = {"official_id": record.official_id, "outcome": "approved", "confidence": 0.9,
                 "vote": {"yeas": 99, "nays": 2},
                 "evidence": {"segment_id": span.key, "quote": span.quote}}
    candidate["vote"]["yeas"] = 9
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(
        200, request=httpx.Request("POST", a[0]),
        json={"choices": [{"message": {"content": dumps({"observations": [candidate]})}}]},
    ))
    issues, _ = assess(Settings(llm_endpoint="http://localhost:9000/chat", llm_model="local"), [record])
    assert len(issues) == 1 and "could not be verified" in issues[0]


def test_invalid_llm_output_retries_and_flags(monkeypatch):
    record = extract([Page(1, AGENDA)], Kind.agenda, False)[0]
    calls = []
    def invalid(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"invalid": True})
    monkeypatch.setattr(httpx, "post", invalid)
    issues, _ = assess(Settings(llm_endpoint="http://localhost:9000/chat", llm_model="local"), [record])
    assert len(calls) == 2
    assert "failed validation" in issues[0]


def test_official_pdf_pair(work):
    import os
    folder = os.environ.get("CIVICLENS_REAL_PDFS")
    if not folder:
        pytest.skip("Set CIVICLENS_REAL_PDFS to directory containing the two official Legistar PDF fixtures")
    record = legistar_january_2019()
    db, config = work
    for spec in record.documents:
        path = Path(folder) / f"669983-{spec.kind}.pdf"
        ingest(record.meeting, spec, payload=path.read_bytes(), bind=db, config=config)
    with Session(db) as session:
        item = session.scalar(select(Item).where(Item.official_id == "2019-025"))
        card = item_card(session, item, detail=True)
        assert item.state == State.approved
        assert "1004 Spencer Street" in card["title"]
        assert card["source"]["page"] == 3
        assert card["timeline"][-1]["details"]["vote"] == {"yeas": 5, "nays": 0}


def test_oversize_attachment_retains_official_link(work):
    db, config = work
    meeting = reference()
    attachment = document(meeting, Kind.attachment)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={
        "Content-Length": str(config.max_pdf_bytes + 1)
    }))
    with httpx.Client(transport=transport) as client:
        assert ingest(meeting, attachment, client=client, bind=db, config=config) == "skipped_size"
    with Session(db) as session:
        sources = meeting_detail(session, session.get(Meeting, meeting.key))["documents"]
        assert len(sources) == 1
        assert sources[0]["url"] == str(attachment.url)
        assert sources[0]["id"] is None


def test_new_sitting_preserves_prior_outcome_without_applying_it_to_revision(work):
    first, later = reference(), reference("test:later", days=12)
    put(work, first, Kind.agenda, AGENDA)
    put(work, first, Kind.minutes, AGENDA + "\n" + MOTION.format(verb="approve"))
    put(work, later, Kind.agenda, AGENDA.replace("25,001.50", "30,001.50"))
    with Session(work[0]) as session:
        item = session.scalars(select(Item)).one()
        card = item_card(session, item, detail=True)
        assert card["status"] == State.scheduled and not card["verified"]
        assert any(row["status"] == State.approved for row in card["timeline"])
