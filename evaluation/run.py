"""Evaluate the public-record pipeline on the manually checked reference sample."""

import argparse
from hashlib import sha256
import json
import statistics
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.orm import Session

from civiclens.config import Settings
from civiclens.db import Base, Document, IngestionRun, Item, ItemEvent, PageText, engine_for
from civiclens.documents import download_pdf
from civiclens.pipeline import ingest
from civiclens.queries import Filters, item_card, search
from civiclens.sources import CIVIC_HOST, public_client
from civiclens.types import DECISIONS, DocumentRef, Kind, MeetingRef


def ratio(number, denominator):
    return round(number / denominator, 4) if denominator else None


def evaluate(reference, pdf_folder, directory):
    config = Settings(database_url=f"sqlite:///{directory / 'eval.db'}", data_dir=directory,
                      embedding_model=None, llm_endpoint=None, llm_model=None)
    db = engine_for(config.database_url)
    Base.metadata.create_all(db)
    counts = {"agenda_labels": 0, "agenda_found": 0, "agenda_page_correct": 0, "amount_tp": 0,
              "amount_fp": 0, "amount_fn": 0, "expected_decisions": 0, "predicted_decisions": 0,
              "matched_decisions": 0, "vote_correct": 0, "decision_page_correct": 0,
              "segment_offsets_checked": 0, "segment_offsets_correct": 0}
    errors = []
    with public_client() as client:
        for source in reference["meetings"]:
            meeting = MeetingRef(key=f"eval:{source['id']}", starts_at=source["date"], body="City Council",
                                 title=f"City Council meeting {source['date'][:10]}",
                                 source_url=f"https://hattiesburgms.portal.civicclerk.com/event/{source['id']}/files")
            for kind in (Kind.agenda, Kind.minutes):
                file_id = source[kind]
                url = f"https://{CIVIC_HOST}/v1/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)"
                spec = DocumentRef(key=f"{meeting.key}:{kind}", kind=kind, url=url,
                                   authoritative=kind == Kind.minutes)
                path = pdf_folder / f"{file_id}.pdf" if pdf_folder else None
                payload = path.read_bytes() if path else download_pdf(client, url, config.max_pdf_bytes)[0]
                if sha256(payload).hexdigest() != source["sha256"][kind]:
                    raise ValueError(f"Source file {file_id} changed since the reference was labeled")
                ingest(meeting, spec, payload=payload, config=config, bind=db)
    with Session(db) as session:
        for source in reference["meetings"]:
            for label in source["items"]:
                counts["agenda_labels"] += 1
                official = label["id"]
                items = session.scalars(select(Item).join(ItemEvent).where(
                    Item.official_id == official, ItemEvent.meeting_key == f"eval:{source['id']}"
                ).distinct()).all()
                cards = [item_card(session, item, detail=True) for item in items if item.visible]
                card = next((card for card in cards if any(event["kind"] == "agenda"
                             and event["meeting"]["key"] == f"eval:{source['id']}" for event in card["timeline"])), None)
                agenda = next((row for row in card["timeline"] if row["kind"] == "agenda"), None) if card else None
                if agenda:
                    counts["agenda_found"] += 1
                    counts["agenda_page_correct"] += int(agenda["evidence"][0]["page"] == label["agenda_page"])
                predicted = {amount["value"] for amount in agenda["details"]["amounts"]} if agenda else set()
                target = set(label["amounts"])
                counts["amount_tp"] += len(predicted & target)
                counts["amount_fp"] += len(predicted - target)
                counts["amount_fn"] += len(target - predicted)
                status = card["status"] if card else "missing"
                counts["expected_decisions"] += int(label["state"] in DECISIONS)
                counts["predicted_decisions"] += int(status in DECISIONS)
                if status != label["state"]:
                    errors.append({"item": official, "expected": label["state"], "observed": status,
                                   "note": label.get("note")})
                elif status in DECISIONS:
                    counts["matched_decisions"] += 1
                    action = next(event for event in card["timeline"]
                                  if event["kind"] == "minutes" and event["status"] == status)
                    counts["decision_page_correct"] += int(card["source"]["page"] == label["decision_page"])
                    vote = action["details"].get("vote") or {}
                    counts["vote_correct"] += int([vote.get("yeas"), vote.get("nays")] == label["vote"])
                for event in card["timeline"] if card else []:
                    for span in event["evidence"]:
                        page = session.get(PageText, (span["document_id"], span["page"]))
                        counts["segment_offsets_checked"] += 1
                        counts["segment_offsets_correct"] += int(
                            page.text[span["start"]:span["end"]] == span["quote"])
        queries = []
        for example in reference["queries"]:
            ids = search(session, Filters(q=example["q"], limit=5))
            ranked = list(dict.fromkeys(session.get(Item, key).official_id for key in ids))
            queries.append({**example, "rank": ranked.index(example["expected"]) + 1
                            if example["expected"] in ranked else None})
        times = session.scalars(select(IngestionRun.duration_ms).where(IngestionRun.status == "processed")).all()
        document_count = len(session.scalars(select(Document.id)).all())
    db.dispose()
    return {
        "evaluation": "July 21 and August 4, 2026 · Hattiesburg City Council",
        "sample_label_count": counts["agenda_labels"],
        "pdfs_processed": document_count,
        "counts": counts,
        "metrics": {
            "agenda_item_recall": ratio(counts["agenda_found"], counts["agenda_labels"]),
            "financial_precision": ratio(counts["amount_tp"], counts["amount_tp"] + counts["amount_fp"]),
            "financial_recall": ratio(counts["amount_tp"], counts["amount_tp"] + counts["amount_fn"]),
            "verified_disposition_precision": ratio(counts["matched_decisions"], counts["predicted_decisions"]),
            "verified_disposition_recall": ratio(counts["matched_decisions"], counts["expected_decisions"]),
            "vote_accuracy_on_verified": ratio(counts["vote_correct"], counts["matched_decisions"]),
            "agenda_pdf_page_accuracy": ratio(counts["agenda_page_correct"], counts["agenda_found"]),
            "decision_pdf_page_accuracy": ratio(counts["decision_page_correct"], counts["matched_decisions"]),
            "search_hit_at_1": ratio(sum(query["rank"] == 1 for query in queries), len(queries)),
            "search_hit_at_5": ratio(sum(query["rank"] is not None for query in queries), len(queries)),
        },
        "queries": queries,
        "decision_errors": errors,
        "processing_ms": {"per_document": times, "median": statistics.median(times)},
        "external_model_cost_usd": 0,
    }


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--pdf-folder", type=Path)
    arguments.add_argument("--output", type=Path)
    args = arguments.parse_args()
    reference = json.loads(Path(__file__).with_name("reference.json").read_text(encoding="utf-8"))
    with TemporaryDirectory() as temp:
        report = evaluate(reference, args.pdf_folder, Path(temp))
    serialized = json.dumps(report, indent=2, ensure_ascii=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
