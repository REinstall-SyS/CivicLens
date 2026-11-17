import argparse
from datetime import date
import json
import logging
from pathlib import Path

from pythonjsonlogger.json import JsonFormatter

from civiclens.config import settings
from civiclens.pipeline import ingest
from civiclens.sources import PUBLIC_HOSTS
from civiclens.types import DiscoveredMeeting


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="civiclens")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Fetch the three verified demonstration meetings")
    sub.add_parser("reindex", help="Rebuild embeddings on existing visible items")
    sub.add_parser("sync", help="Discover recent and upcoming meetings")
    sub.add_parser("schedule", help="Serve a Prefect deployment on a six-hour cadence")
    backfill = sub.add_parser("backfill", help="Fetch an official half-open local date range")
    backfill.add_argument("start", type=date.fromisoformat)
    backfill.add_argument("end", type=date.fromisoformat)
    manual = sub.add_parser("import-pdf", help="Import a sourced public PDF through the same pipeline")
    manual.add_argument("manifest", type=Path, help="JSON meeting and document metadata")
    manual.add_argument("pdf", type=Path)
    audio = sub.add_parser("transcribe", help="Transcribe an operator-supplied official recording")
    audio.add_argument("media", type=Path)
    audio.add_argument("official_record", help="Official Hattiesburg page publishing the recording")
    audio.add_argument("--model", default="base")
    return root


def main() -> None:
    args = parser().parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("civiclens")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    if args.command == "reindex":
        from civiclens.intelligence import reindex

        result = {"items_indexed": reindex(settings())}
    elif args.command == "transcribe":
        from civiclens.audio import transcribe

        result = transcribe(args.media, args.official_record, settings().data_dir, args.model)
    elif args.command == "import-pdf":
        manifest = DiscoveredMeeting.model_validate_json(args.manifest.read_text(encoding="utf-8"))
        if len(manifest.documents) != 1:
            raise SystemExit("The import manifest must describe one PDF")
        document = manifest.documents[0]
        if document.url.scheme != "https" or document.url.host not in PUBLIC_HOSTS:
            raise SystemExit("Provide an official Hattiesburg PDF source URL")
        with args.pdf.open("rb") as stream:
            payload = stream.read(settings().max_pdf_bytes + 1)
        result = ingest(manifest.meeting, document, payload=payload)
    else:
        from civiclens.workflows import backfill, bootstrap, sync

        if args.command == "schedule":
            sync.serve(name="every-six-hours", cron="12 */6 * * *")
            return
        if args.command == "backfill":
            result = backfill(args.start, args.end)
        elif args.command == "bootstrap":
            result = bootstrap()
        else:
            result = sync()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
