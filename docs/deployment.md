# Deployment

## Configuration

Start with the root `.env.example`. For shared access, use HTTPS with a reverse proxy, set `CORS_ORIGIN` to the browser origin, and set `SECURE_COOKIES=true`. The Compose ports bind to localhost. Expose the web tier through the reverse proxy. Keep Prefect and the API on the service network or on a private administrative connection. Apply proxy request size limits for the admin import route and ordinary rate limits at the public entry point.

Use a fresh PostgreSQL password and a generated reviewer token in the deployment secret store. Compose interpolates the password into a connection URL, so use a URL-safe value. Configure service credentials through environment injection when running outside Compose. The included reviewer token implements one shared local reviewer identity. A team deployment should place review routes behind its identity provider and map reviewers to separate identities.

PostgreSQL needs the `vector` extension and a user allowed to create it on the first migration, or a DBA can install the extension before `alembic upgrade head`. Subsequent ingestion must have write access to the civic tables and the PDF volume. `/healthz` checks process liveness. `/readyz` checks that the database schema is reachable.

## Advanced processing

**Model-assisted review.** Set `LLM_ENDPOINT` to the full chat-completions URL of a compatible local service, including the path, and set `LLM_MODEL` to the served model identifier. An optional `LLM_API_KEY` is used as a bearer token. The model sees bounded evidence spans and returns strict JSON. Unsupported outcomes and vote claims enter the review queue. The default deterministic pipeline runs without model access. Treat the configured endpoint as a recipient of the public document excerpts it receives.

**Hybrid retrieval.** Set `PYTHON_EXTRAS=[semantic]` and `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`. Rebuild the worker and API images with the extras enabled. Configure the same model in both services. The vector type uses 384 dimensions. PostgreSQL uses GIN full-text search, cosine distance, and reciprocal rank fusion. For existing records, run `civiclens reindex` after enabling or changing the model. Model files can be preloaded into the approved cache in environments with restricted network access.

**OCR.** The API image supplies Tesseract English data. On a workstation, set `TESSDATA_PREFIX` to the directory containing `eng.traineddata`, or set `TESSDATA` in the root `.env`. The application records OCR provenance and preserves extracted character offsets. OCR-only dispositions enter human review.

**Windows Prefect dependency.** If Windows blocks `whenever._whenever`, install the upstream universal wheel of the same version already required by Prefect:

```powershell
$version = python -c "import importlib.metadata as m; print(m.version('whenever'))"
python -m pip download --platform any --only-binary=:all: --no-deps --dest .data "whenever==$version"
python -m pip install --no-deps --force-reinstall ".data/whenever-$version-py3-none-any.whl"
```

## Import an official PDF

Use the admin dashboard or the CLI. Keep the meeting key and document key stable across manual revisions. Provide a source URL served by an allowed Hattiesburg public records host, the original bytes, and an RFC 3339 meeting timestamp with its offset. Set `authoritative` only when the source is published as an official final outcome record.

A manifest describes one document. This manifest points to the genuine January 2019 agenda:

```json
{
  "meeting": {
    "key": "legistar:669983",
    "body": "City Council",
    "title": "City Council regular meeting",
    "starts_at": "2019-01-08T17:00:00-06:00",
    "location": "Council Chambers",
    "status": "held",
    "source_url": "https://hattiesburgms.legistar.com/MeetingDetail.aspx?GUID=79BB73AB-68B9-4536-8377-CC04C4B0E56B&ID=669983&Search="
  },
  "documents": [
    {
      "key": "legistar:669983:agenda",
      "kind": "agenda",
      "url": "https://hattiesburgms.legistar.com/View.ashx?GUID=79BB73AB-68B9-4536-8377-CC04C4B0E56B&ID=669983&M=A",
      "authoritative": false
    }
  ]
}
```

```sh
civiclens import-pdf manifest.json 669983-agenda.pdf
```

Operator settings `MAX_PDF_BYTES` and `MAX_PDF_PAGES` bound document work. Oversize attachments retain a publisher link and are marked `skipped_size`. An import with the same checksum and authority leaves the current revision intact. Conditional HTTP validators, a short recheck window, and SHA-256 comparison limit repeated work.

## Operations

- Back up the PostgreSQL database and the content-addressed PDF volume together. Keep the Prefect database volume if you need orchestration history. Verify restores by reopening a cited PDF and comparing its digest with the database.
- Review the admin queue and ingestion ledger after a source layout changes. Run affected dates again after fixing a transient issue. Failed revisions leave the last committed record available.
- Reprocess affected windows after bumping the extraction version. Old citations and revisions remain addressable. The scheduled window is bounded to a delayed-minutes lookback and a future calendar window. Use explicit backfills for earlier corrections.
- Track the ratio of unsupported layouts and unverified outcomes by government body. The checked-in reference evaluation is a small regression benchmark.
- Browser watch identities are single-device. Notification delivery is the in-app inbox. The API uses secure cookie configuration for HTTPS deployments.
## Optional transcription

The transcription command accepts a locally available public recording and the official record URL publishing it. Its timecoded JSON stays in the local archive for review. The demo PDFs and meetings do not depend on recordings.

\`\`\`sh
python -m pip install -e ".[audio]"
civiclens transcribe meeting.mp3 'https://hattiesburgms.legistar.com/MeetingDetail.aspx?...'
\`\`\`

The sample has no verified recording for a transcription benchmark. Geographic matching uses recorded text and makes no parcel-impact determination. The PDF parser is provided under PyMuPDF's upstream AGPL or commercial terms. [PyMuPDF license](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
