"""Version 1 of the public API."""

from fastapi import APIRouter

from app.api.v1 import ask, corpus, health

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(corpus.router)
api_router.include_router(ask.router)

__all__ = ["api_router"]
