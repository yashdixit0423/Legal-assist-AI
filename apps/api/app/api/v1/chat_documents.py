"""``/v1/chat/documents`` — temporary document context for Chat (docs/adr/0005).

The body is parsed **as it arrives**, chunk by chunk, and only the ``file``
part is kept. The moment that part passes 10 MB the read stops with
``file_too_large``: the server never buffers a whole oversized body to find
out it is oversized, and never holds more than the limit plus one chunk.
A ``Content-Length`` over the limit is refused before reading anything.

FastAPI's ``UploadFile`` is deliberately not used: Starlette spools any part
over 1 MB to a temporary file, and "nothing uploaded is written to disk" is a
rule here, not a preference.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Path, Request, Response
from python_multipart.multipart import MultipartParser, parse_options_header

from app.api.deps import CurrentUser, SettingsDep
from app.core import ratelimit
from app.core.errors import InvalidRequestError
from app.core.logging import get_logger
from app.schemas.documents import DocumentResponse
from app.services.documents.extract import (
    MAX_BYTES,
    FileTooLargeError,
    display_filename,
    extract,
)
from app.services.documents.retrieve import build_chunks, embed_chunks
from app.services.documents.store import StoredDocument, get_store, new_document_id

router = APIRouter(prefix="/chat/documents", tags=["chat"])
logger = get_logger(__name__)

UPLOADS_PER_HOUR = 30
# Room for the multipart envelope and any small non-file fields.
ENVELOPE_BYTES = 64 * 1024
MAX_BODY_BYTES = MAX_BYTES + ENVELOPE_BYTES

DocumentId = Annotated[str, Path(min_length=8, max_length=64)]


class FileUploadReader:
    """An incremental multipart reader that keeps only the ``file`` part.

    ``feed`` takes the body one chunk at a time. Bytes of other parts are
    counted and dropped; bytes of the file part are kept, and the first byte
    past ``max_file_bytes`` raises :class:`FileTooLargeError` mid-stream.
    ``peak_file_bytes`` records the most ever held, for the tests.
    """

    def __init__(
        self,
        content_type: str,
        *,
        max_file_bytes: int = MAX_BYTES,
        max_body_bytes: int = MAX_BODY_BYTES,
    ) -> None:
        mime, params = parse_options_header(content_type)
        boundary = params.get(b"boundary")
        if mime != b"multipart/form-data" or not boundary:
            raise InvalidRequestError("Send the document as multipart/form-data in a 'file' field.")
        self.max_file_bytes = max_file_bytes
        self.max_body_bytes = max_body_bytes
        self.received = 0
        self.peak_file_bytes = 0
        self._file = bytearray()
        self._filename: str | None = None
        self._found = False
        self._in_file = False
        self._headers: dict[bytes, bytes] = {}
        self._field = bytearray()
        self._value = bytearray()
        self._parser = MultipartParser(
            boundary,
            {
                "on_part_begin": self._part_begin,
                "on_header_field": self._header_field,
                "on_header_value": self._header_value,
                "on_header_end": self._header_end,
                "on_headers_finished": self._headers_finished,
                "on_part_data": self._part_data,
            },
        )

    def _part_begin(self) -> None:
        self._headers = {}
        self._in_file = False

    def _header_field(self, data: bytes, start: int, end: int) -> None:
        self._field.extend(data[start:end])

    def _header_value(self, data: bytes, start: int, end: int) -> None:
        self._value.extend(data[start:end])

    def _header_end(self) -> None:
        self._headers[bytes(self._field).lower()] = bytes(self._value)
        self._field.clear()
        self._value.clear()

    def _headers_finished(self) -> None:
        _, disposition = parse_options_header(self._headers.get(b"content-disposition", b""))
        if disposition.get(b"name") == b"file" and not self._found:
            self._found = self._in_file = True
            raw = disposition.get(b"filename")
            self._filename = raw.decode("utf-8", "replace") if raw else None

    def _part_data(self, data: bytes, start: int, end: int) -> None:
        if not self._in_file:
            return  # other fields: counted in `received`, never kept
        if len(self._file) + (end - start) > self.max_file_bytes:
            raise FileTooLargeError()
        self._file.extend(data[start:end])
        self.peak_file_bytes = max(self.peak_file_bytes, len(self._file))

    def feed(self, chunk: bytes) -> None:
        self.received += len(chunk)
        if self.received > self.max_body_bytes:
            raise FileTooLargeError()
        try:
            self._parser.write(chunk)
        except FileTooLargeError:
            raise
        except Exception as exc:  # noqa: BLE001 — any framing error is a bad request
            raise InvalidRequestError("The upload could not be read.") from exc

    def finish(self) -> tuple[str | None, bytes]:
        try:
            self._parser.finalize()
        except Exception as exc:  # noqa: BLE001
            raise InvalidRequestError("The upload could not be read.") from exc
        if not self._found:
            raise InvalidRequestError("Send the document in a 'file' field.")
        return self._filename, bytes(self._file)


async def _read_file_part(request: Request) -> tuple[str | None, bytes]:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise FileTooLargeError()
    reader = FileUploadReader(request.headers.get("content-type", ""))
    async for chunk in request.stream():
        reader.feed(chunk)
    return reader.finish()


@router.post(
    "",
    status_code=201,
    response_model=DocumentResponse,
    summary="Attach a document to the caller's Chat, in memory, for one hour of idle time",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
    responses={
        413: {"description": "Over 10 MB, over 300 pages, or too much text (file_too_large)."},
        415: {"description": "Not a PDF, DOCX or UTF-8 text file (unsupported_file_type)."},
        422: {"description": "No readable text, e.g. a scanned PDF (document_unreadable)."},
    },
)
async def upload_document(
    request: Request, user: CurrentUser, settings: SettingsDep
) -> DocumentResponse:
    """Read, chunk and embed a document. Nothing is written to disk or logged.

    The response is metadata only — the text is never sent back here.
    """
    if settings.RATE_LIMIT_ENABLED:
        await ratelimit.enforce(
            settings,
            key=f"chat-doc-upload:{user.id}",
            limit=UPLOADS_PER_HOUR,
            window_seconds=3600,
        )
    raw_name, data = await _read_file_part(request)
    filename = display_filename(raw_name)

    extracted = await asyncio.to_thread(extract, data)
    del data
    chunks = await asyncio.to_thread(build_chunks, settings, filename, extracted)
    embedded = await asyncio.to_thread(embed_chunks, settings, chunks)

    store = get_store()
    document = store.put(
        StoredDocument(
            id=new_document_id(),
            user_id=str(user.id),
            filename=filename,
            kind=extracted.kind,
            locator_kind=extracted.locator_kind,
            pages=extracted.pages,
            chunks=embedded,
        )
    )
    # Counts only: no filename (it can itself be sensitive) and no text.
    logger.info(
        "chat_document_stored",
        kind=extracted.kind,
        pages=extracted.pages,
        chunks=len(embedded),
        chars=extracted.char_count,
    )
    return DocumentResponse(
        document_id=document.id,
        filename=document.filename,
        kind=document.kind,
        pages=document.pages,
        chunk_count=len(document.chunks),
        expires_at=store.expires_at(document),
    )


@router.delete(
    "/{document_id}",
    status_code=204,
    summary="Forget a document now rather than at its expiry",
    responses={404: {"description": "Unknown, expired or not yours (document_not_found)."}},
)
async def delete_document(document_id: DocumentId, user: CurrentUser) -> Response:
    get_store().delete(str(user.id), document_id)
    return Response(status_code=204)
