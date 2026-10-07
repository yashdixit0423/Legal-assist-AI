"""Version 1 of the public API.

Only ``/v1/ask``, ``/v1/chat/documents`` and the ``/v1/credentials`` routes
require authentication.
Health, the corpus reads and search are deliberately open: spec §06 requires
that reading the law needs no credentials.
"""

from fastapi import APIRouter

from app.api.v1 import ask, auth, chat_documents, corpus, health

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(corpus.router)
api_router.include_router(ask.router)
api_router.include_router(chat_documents.router)

__all__ = ["api_router"]
