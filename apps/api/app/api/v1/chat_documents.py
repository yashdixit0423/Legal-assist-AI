"""``/v1/chat/documents`` — temporary document context for Chat (docs/adr/0005).

The body is read off the stream with a hard byte cap and parsed in memory.
FastAPI's ``UploadFile`` is deliberately not used: Starlette spools any part
over 1 MB to a temporary file, and "nothing uploaded is written to disk" is a
rule here, not a preference. The cap also means a client cannot make the
server read a gigabyte just to refuse it.
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
# The file plus generous room for the multipart envelope.
MAX_BODY_BYTES = MAX_BYTES + 64 * 1024

DocumentId = Annotated[str, Path(min_length=8, max_length=64)]


async def _read_capped(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise FileTooLargeError()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise FileTooLargeError()
    return bytes(body)


def _parse_file_part(content_type: str, body: bytes) -> tuple[str | None, bytes]:
    """The ``file`` part of a multipart body: (filename, bytes). In memory only."""
    mime, params = parse_options_header(content_type)
    boundary = params.get(b"boundary")
    if mime != b"multipart/form-data" or not boundary:
        raise InvalidRequestError("Send the document as multipart/form-data in a 'file' field.")

    parts: list[dict[str, object]] = []
    header_field = bytearray()
    header_value = bytearray()

    def on_part_begin() -> None:
        parts.append({"headers": {}, "data": bytearray()})

    def on_header_field(data: bytes, start: int, end: int) -> None:
        header_field.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        header_value.extend(data[start:end])

    def on_header_end() -> None:
        headers = parts[-1]["headers"]
        assert isinstance(headers, dict)  # noqa: S101 — narrowing for mypy
        headers[bytes(header_field).lower()] = bytes(header_value)
        header_field.clear()
        header_value.clear()

    def on_part_data(data: bytes, start: int, end: int) -> None:
        buffer = parts[-1]["data"]
        assert isinstance(buffer, bytearray)  # noqa: S101 — narrowing for mypy
        buffer.extend(data[start:end])

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_part_data": on_part_data,
        },
        max_size=MAX_BODY_BYTES,
    )
    try:
        parser.write(body)
        parser.finalize()
    except Exception as exc:  # noqa: BLE001 — any framing error is a bad request
        raise InvalidRequestError("The upload could not be read.") from exc

    for part in parts:
        headers = part["headers"]
        data = part["data"]
        assert isinstance(headers, dict) and isinstance(data, bytearray)  # noqa: S101
        _, disposition = parse_options_header(headers.get(b"content-disposition", b""))
        if disposition.get(b"name") == b"file":
            raw_name = disposition.get(b"filename")
            name = raw_name.decode("utf-8", "replace") if raw_name else None
            return name, bytes(data)
    raise InvalidRequestError("Send the document in a 'file' field.")


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
    body = await _read_capped(request)
    raw_name, data = _parse_file_part(request.headers.get("content-type", ""), body)
    del body
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
