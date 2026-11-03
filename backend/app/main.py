"""FastAPI application factory. Run with ``uvicorn app.main:app --reload``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.analysis.router import router as analysis_router
from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import DomainError
from app.core.router import router as system_router
from app.eln.router import router as eln_router
from app.memory.router import router as memory_router
from app.partner.router import router as partner_router


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
        db.create_all()
        if settings.auto_seed:
            from app.seed.loader import seed_if_empty

            with db.session() as session:
                seed_if_empty(session)
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
        )

    for router in (system_router, eln_router, memory_router, analysis_router, partner_router):
        app.include_router(router)
    return app


app = create_app()
