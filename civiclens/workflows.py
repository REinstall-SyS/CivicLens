from datetime import date, datetime, timedelta

from prefect import flow, task

from civiclens.pipeline import ingest, register
from civiclens.sources import HattiesburgCivicClerk, legistar_january_2019, public_client
from civiclens.types import LOCAL, DiscoveredMeeting, DocumentRef, MeetingRef


@task(retries=2, retry_delay_seconds=[5, 30], persist_result=False)
def discover(start: date, end: date) -> list[DiscoveredMeeting]:
    with public_client() as client:
        return HattiesburgCivicClerk(client).discover(start, end)


@task(retries=2, retry_delay_seconds=[5, 30], persist_result=False)
def ingest_document(meeting: MeetingRef, source: DocumentRef) -> str:
    with public_client() as client:
        return ingest(meeting, source, client=client)


def run_records(records: list[DiscoveredMeeting]) -> dict:
    outcomes = {}
    failures = []
    for record in records:
        register(record.meeting, record.documents)
        for document in record.documents:
            try:
                outcomes[document.key] = ingest_document(record.meeting, document)
            except Exception:
                failures.append(document.key)
    if failures:
        raise RuntimeError("Failed documents after retries: " + ", ".join(failures))
    return outcomes


@flow(name="Hattiesburg backfill", log_prints=True)
def backfill(start: date, end: date) -> dict:
    return run_records(discover(start, end))


@flow(name="Hattiesburg public-record discovery", log_prints=True)
def sync() -> dict:
    today = datetime.now(LOCAL).date()
    return run_records(discover(today - timedelta(days=120), today + timedelta(days=90)))


@flow(name="CivicLens source bootstrap", log_prints=True)
def bootstrap() -> dict:
    records = discover(date(2026, 9, 8), date(2026, 9, 16))
    samples = [legistar_january_2019()]
    for record in records:
        if record.meeting.key in {"civicclerk:1618", "civicclerk:1621"}:
            samples.append(DiscoveredMeeting(meeting=record.meeting, documents=[
                document for document in record.documents if document.kind in {"agenda", "minutes"}
            ]))
    if len(samples) != 3:
        raise ValueError("The official feed did not return both demonstration meetings")
    return run_records(samples)
