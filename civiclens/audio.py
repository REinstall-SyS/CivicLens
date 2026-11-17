"""Optional, operator-initiated transcription of a sourced local recording."""

from hashlib import file_digest, sha256
from importlib.metadata import version
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from civiclens.sources import PUBLIC_HOSTS


def transcribe(media: Path, official_record: str, root: Path, model: str) -> dict:
    """Archive timecodes and verbatim model output with provenance."""
    from faster_whisper import WhisperModel

    origin = urlsplit(official_record)
    if origin.scheme != "https" or origin.hostname not in PUBLIC_HOSTS | {"hattiesburgms.portal.civicclerk.com"} or origin.username:
        raise ValueError("Provide the official Hattiesburg record that publishes the recording")
    with media.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    method = f"faster-whisper/{version('faster-whisper')}"
    key = sha256(f"{digest}:{official_record}:{method}:{model}".encode()).hexdigest()
    destination = root / "transcripts" / f"{key}.json"
    if destination.is_file():
        return {"status": "unchanged", "path": str(destination)}

    engine = WhisperModel(model, device="cpu", compute_type="int8")
    segments, metadata = engine.transcribe(str(media), vad_filter=True)
    record = {
        "official_record_url": official_record, "recording_sha256": digest,
        "method": method, "model": model, "language": metadata.language,
        "segments": [{"start_seconds": round(segment.start, 3), "end_seconds": round(segment.end, 3),
                      "text": segment.text.strip()} for segment in segments],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, delete=False, mode="w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        temporary = Path(stream.name)
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "processed", "path": str(destination), "segments": len(record["segments"])}
