"""Reading a user's document, in memory — docs/adr/0005.

The bytes are never written anywhere. The type is decided from the bytes
themselves, because a client's ``Content-Type`` and filename are claims, not
facts: a PDF renamed ``.txt`` is a PDF, and an executable renamed ``.pdf`` is
refused.

Three layouts come out of this module, and the citation id a model uses for a
passage follows from them:

* PDF → one segment per page, cited ``D<n>-p<page>``;
* DOCX and TXT → one segment per paragraph, cited ``D<n>-para<k>``. They have
  no pages, so "page 4" would be invented.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Any, Literal

from app.core.errors import LegalEdgeError

DocumentKind = Literal["pdf", "txt", "docx"]
LocatorKind = Literal["page", "para"]

MAX_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_TEXT_CHARS = 400_000
# A DOCX is a ZIP. These bound what python-docx is allowed to inflate, so a
# 10 MB upload cannot expand into gigabytes of XML (a zip bomb).
MAX_DOCX_UNCOMPRESSED = 60 * 1024 * 1024
MAX_DOCX_ENTRIES = 5000
# Below this many characters across a whole PDF there is no text layer worth
# reading: it is a scan, and OCR is out of scope.
MIN_TEXT_CHARS = 20


class UnsupportedFileTypeError(LegalEdgeError):
    code = "unsupported_file_type"
    http_status = 415
    message = "Only PDF, TXT and DOCX documents are supported."


class FileTooLargeError(LegalEdgeError):
    code = "file_too_large"
    http_status = 413
    message = "Documents can be up to 10 MB."


class DocumentUnreadableError(LegalEdgeError):
    code = "document_unreadable"
    http_status = 422
    message = "No readable text was found in that document."


@dataclass(frozen=True)
class Segment:
    """One page (PDF) or one paragraph (DOCX/TXT) of extracted text."""

    locator: int
    text: str


@dataclass(frozen=True)
class Extracted:
    kind: DocumentKind
    locator_kind: LocatorKind
    segments: list[Segment]
    pages: int | None

    @property
    def char_count(self) -> int:
        return sum(len(segment.text) for segment in self.segments)


# --- type detection ---------------------------------------------------------


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _decode_text(data: bytes) -> str | None:
    """UTF-8 (with or without a BOM) and no NUL bytes, or not text at all."""
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def detect_kind(data: bytes) -> DocumentKind:
    """Decide the type from the bytes alone."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        if _is_docx(data):
            return "docx"
        raise UnsupportedFileTypeError()
    if _decode_text(data) is not None:
        return "txt"
    raise UnsupportedFileTypeError()


# --- normalisation ----------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_RUNS = re.compile(r"\n{3,}")
_SPACE_RUNS = re.compile(r"[ \t ]{2,}")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _CONTROL.sub("", text)
    text = _SPACE_RUNS.sub(" ", text)
    return _BLANK_RUNS.sub("\n\n", text).strip()


def _enforce_text_cap(segments: list[Segment]) -> None:
    if sum(len(segment.text) for segment in segments) > MAX_TEXT_CHARS:
        raise FileTooLargeError(
            "That document has more text than can be read at once. "
            "Try attaching the relevant part on its own."
        )


# --- extractors -------------------------------------------------------------


def _extract_pdf(data: bytes) -> Extracted:
    import fitz

    try:
        document: Any = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — any parser failure is "unreadable"
        raise DocumentUnreadableError("That PDF could not be opened.") from exc
    try:
        if document.needs_pass:
            raise DocumentUnreadableError("That PDF is password-protected.")
        if document.page_count > MAX_PDF_PAGES:
            raise FileTooLargeError(f"PDFs can be up to {MAX_PDF_PAGES} pages.")
        segments = []
        for index in range(document.page_count):
            text = _clean(document.load_page(index).get_text("text"))
            if text:
                segments.append(Segment(locator=index + 1, text=text))
        pages = int(document.page_count)
    finally:
        document.close()

    if sum(len(segment.text) for segment in segments) < MIN_TEXT_CHARS:
        raise DocumentUnreadableError(
            "That PDF has no text layer — it looks like a scan. "
            "Scanned documents can't be read yet."
        )
    _enforce_text_cap(segments)
    return Extracted(kind="pdf", locator_kind="page", segments=segments, pages=pages)


def _paragraphs(blocks: list[str]) -> list[Segment]:
    """Number non-empty paragraphs from 1, in reading order."""
    cleaned = [_clean(block) for block in blocks]
    return [
        Segment(locator=number, text=text)
        for number, text in enumerate((text for text in cleaned if text), start=1)
    ]


def _extract_docx(data: bytes) -> Extracted:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if (
            len(infos) > MAX_DOCX_ENTRIES
            or sum(info.file_size for info in infos) > MAX_DOCX_UNCOMPRESSED
        ):
            raise FileTooLargeError("That DOCX expands to more than can be read safely.")

    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document: Any = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — any parser failure is "unreadable"
        raise DocumentUnreadableError("That DOCX could not be opened.") from exc

    # Body order matters for paragraph numbering, so walk the XML children
    # rather than `document.paragraphs` (which skips tables entirely).
    blocks: list[str] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            blocks.append(Paragraph(child, document).text)
        elif tag == "tbl":
            for row in Table(child, document).rows:
                cells = [cell.text.strip() for cell in row.cells]
                blocks.append(" | ".join(cell for cell in cells if cell))

    segments = _paragraphs(blocks)
    if sum(len(segment.text) for segment in segments) < MIN_TEXT_CHARS:
        raise DocumentUnreadableError()
    _enforce_text_cap(segments)
    return Extracted(kind="docx", locator_kind="para", segments=segments, pages=None)


def _extract_txt(data: bytes) -> Extracted:
    text = _decode_text(data)
    if text is None:
        raise UnsupportedFileTypeError("Text files must be UTF-8.")
    segments = _paragraphs(re.split(r"\n\s*\n", text.replace("\r\n", "\n")))
    if sum(len(segment.text) for segment in segments) < MIN_TEXT_CHARS:
        raise DocumentUnreadableError()
    _enforce_text_cap(segments)
    return Extracted(kind="txt", locator_kind="para", segments=segments, pages=None)


def extract(data: bytes) -> Extracted:
    """Detect the type and extract the text, or raise a typed error."""
    if len(data) > MAX_BYTES:
        raise FileTooLargeError()
    if not data:
        raise DocumentUnreadableError("That file is empty.")
    kind = detect_kind(data)
    if kind == "pdf":
        return _extract_pdf(data)
    if kind == "docx":
        return _extract_docx(data)
    return _extract_txt(data)


# --- filenames --------------------------------------------------------------

_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f<>\"`]")


def display_filename(raw: str | None) -> str:
    """A filename fit to show back to its owner — and nothing else.

    It is never used as a path. Directory parts are dropped anyway, because a
    name like ``../../etc/passwd`` should not even *look* like a path in the UI
    or in a prompt attribute.
    """
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_NAME.sub("", unicodedata.normalize("NFC", name))
    name = re.sub(r"\s+", " ", name).strip().lstrip(".")
    return name[:120] or "document"
