"""FastAPI application factory. Run with ``uvicorn app.main:app --reload``."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.analysis.router import router as analysis_router
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import DomainError
from app.core.limits import RequestLimitMiddleware, SecurityHeadersMiddleware
from app.core.router import router as system_router
from app.eln.router import router as eln_router
from app.memory.router import router as memory_router
from app.memory.service import sync_search_index
from app.partner.router import router as partner_router
from app.wiring import install as install_memory_fact_providers

logger = logging.getLogger("app")

#: Longest request value echoed back in a 422 ``detail[].input`` (bytes of JSON).
MAX_ECHOED_INPUT = 200


class ErrorBody(BaseModel):
    """Error envelope for every :class:`DomainError`."""

    code: str
    message: str


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    """Build the app. Tests pass their own in-memory ``Database``."""
    settings = settings or get_settings()
    db = database or Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        db.prepare_schema()  # Alembic: empty → create_all + stamp, managed → upgrade head
        if settings.auto_seed:
            from app.seed.loader import seed_if_empty

            with db.session() as session:
                seed_if_empty(session, settings.seed_profile)
                session.commit()
        with db.session() as session:  # derived search index: written here, never on GET
            sync_search_index(session)
            session.commit()
        yield

    app = FastAPI(
        title="BioPilot API",
        version=__version__,
        description="AI Research Partner — ELN · Research Memory · Scientific Analysis · Partner",
        lifespan=lifespan,
        responses={400: {"model": ErrorBody}, 404: {"model": ErrorBody}, 409: {"model": ErrorBody}},
    )
    app.state.db = db
    install_memory_fact_providers()
    app.add_middleware(
        RequestLimitMiddleware,
        max_request_bytes=settings.max_request_bytes,
        max_json_bytes=settings.max_json_bytes,
        max_json_depth=settings.max_json_depth,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    # Added last = outermost, so 413/400 rejections above still carry CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
        expose_headers=["X-Total-Count"],
        allow_credentials=False,
    )
    if "*" in settings.cors_origins:
        logger.warning("BIOPILOT_CORS_ORIGINS contains '*': any website may call this API")

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
        )

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI's 422 shape, with echoed ``input`` values truncated (no 5 MB echoes)."""
        return JSONResponse(
            status_code=422, content={"detail": [_compact_error(e) for e in exc.errors()]}
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_request: Request, exc: IntegrityError) -> JSONResponse:
        """A constraint race the service did not resolve: 409, never the SQL text."""
        logger.warning("integrity conflict: %s", exc.orig)
        return JSONResponse(
            status_code=409,
            content={
                "code": "conflict",
                "message": "동시에 같은 기록이 변경되었습니다 — 다시 시도하세요",
            },
        )

    @app.exception_handler(Exception)
    async def _internal(_request: Request, exc: Exception) -> JSONResponse:
        """Unexpected failure: log the traceback, return only a generic envelope."""
        logger.error("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "서버 내부 오류가 발생했습니다"},
        )

    for router in (system_router, eln_router, memory_router, analysis_router, partner_router):
        app.include_router(router)
    return app


def _compact_error(error: Any) -> Any:
    """One pydantic error as JSON, with a long ``input`` replaced by a short preview."""
    out = jsonable_encoder(error, custom_encoder={str: _printable})
    if "input" in out:
        raw = json.dumps(out["input"], ensure_ascii=False)
        if len(raw) > MAX_ECHOED_INPUT:
            out["input"] = raw[:MAX_ECHOED_INPUT] + "…"
    return out


def _printable(text: str) -> str:
    """``text`` with unpaired surrogates escaped, so the response can be UTF-8 encoded."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


app = create_app()
