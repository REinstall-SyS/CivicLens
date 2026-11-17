from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

import httpx
import pymupdf

from civiclens.config import Settings
from civiclens.sources import PUBLIC_HOSTS


class DocumentError(ValueError):
    pass


class DocumentLimitError(DocumentError):
    pass


@dataclass(frozen=True)
class Page:
    number: int
    text: str
    method: str = "text"


def download_pdf(client: httpx.Client, url: str, limit: int,
                 headers: dict | None = None) -> tuple[bytes | None, httpx.Headers]:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in PUBLIC_HOSTS or parts.username:
        raise DocumentError("Download URL is outside the official public source allowlist")
    with client.stream("GET", url, headers=headers, follow_redirects=False) as response:
        if response.status_code == 304:
            return None, response.headers
        response.raise_for_status()
        length = response.headers.get("content-length", "")
        if length.isdecimal() and int(length) > limit:
            raise DocumentLimitError("PDF exceeds the configured byte limit")
        payload = bytearray()
        for chunk in response.iter_bytes():
            payload.extend(chunk)
            if len(payload) > limit:
                raise DocumentLimitError("PDF exceeds the configured byte limit")
        if not payload.startswith(b"%PDF-"):
            raise DocumentError("The official URL did not return a PDF")
        return bytes(payload), response.headers


def store_pdf(root: Path, payload: bytes) -> tuple[str, Path]:
    digest = sha256(payload).hexdigest()
    destination = root / "raw" / digest[:2] / f"{digest}.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        with NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
            temporary.write(payload)
        temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    return digest, destination


def read_pdf(payload: bytes, config: Settings) -> tuple[list[Page], list[int]]:
    if len(payload) > config.max_pdf_bytes or not payload.startswith(b"%PDF-"):
        raise DocumentError("Expected a PDF within the configured byte limit")
    pages, failures = [], []
    with pymupdf.open(stream=payload, filetype="pdf") as document:
        if document.needs_pass or len(document) > config.max_pdf_pages:
            raise DocumentError("PDF is encrypted or exceeds the configured page limit")
        for number, page in enumerate(document, start=1):
            text = page.get_text(sort=True)
            method = "text"
            if sum(letter.isalnum() for letter in text) < config.ocr_min_chars:
                try:
                    ocr = page.get_textpage_ocr(language="eng", dpi=config.ocr_dpi, full=True,
                                                 tessdata=config.tessdata)
                    recovered = page.get_text(textpage=ocr, sort=True)
                    if len(recovered.strip()) > len(text.strip()):
                        text, method = recovered, "ocr"
                    elif not text.strip():
                        failures.append(number)
                except (RuntimeError, ValueError):
                    failures.append(number)
            # Offsets always refer to this persisted text, including spaces.
            pages.append(Page(number, text.replace("\r\n", "\n"), method))
    return pages, failures
