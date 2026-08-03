"""FastAPI application factory: middleware, exception handlers, routers,
and liveness/readiness checks."""

from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import cast

from arq import create_pool
from arq.connections import RedisSettings
from arq.constants import default_queue_name as ARQ_QUEUE_NAME
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.common.schemas import ApiErrorResponse
from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import CMIPError
from app.core.logging import configure_logging, get_logger
from app.core.metrics import queue_length
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import get_redis_client
from app.modules.audit.api import router as audit_router
from app.modules.auth.admin_api import router as roles_router
from app.modules.auth.admin_api import users_admin_router
from app.modules.auth.api import router as auth_router
from app.modules.auth.api import users_router as auth_users_router
from app.modules.documents.api import jobs_router as processing_jobs_router
from app.modules.documents.api import router as documents_router
from app.modules.extraction.api import router as extraction_router
from app.modules.extraction.api import runs_router as extraction_runs_router
from app.modules.extraction.api import tables_router as extraction_tables_router
from app.modules.extraction.trust.api import entities_router as trust_entities_router
from app.modules.extraction.trust.api import review_queue_router as trust_review_queue_router
from app.modules.extraction.trust.api import runs_router as trust_runs_router
from app.modules.extraction.trust.api import trust_runs_router as trust_pipeline_runs_router
from app.modules.graph.api import (
    graph_edges_router,
    graph_entity_router,
    graph_nodes_router,
    graph_relationships_router,
    graph_router,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("application_starting")
    yield
    await app.state.arq_pool.aclose()
    await engine.dispose()
    logger.info("application_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="AI Commodity Market Intelligence Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(CMIPError)
    async def handle_cmip_error(request: Request, exc: CMIPError) -> JSONResponse:
        logger.warning(
            "request_failed", path=request.url.path, error_code=exc.error_code, message=exc.message
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiErrorResponse(
                error_code=exc.error_code, message=exc.message, details=exc.details
            ).model_dump(),
        )

    @app.get("/health", tags=["Health"])
    async def liveness() -> dict[str, str]:
        """Liveness: is the process up? No dependency checks - a DB outage
        should not make the orchestrator kill and restart a healthy pod."""
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    async def readiness() -> dict[str, str]:
        """Readiness: can this instance actually serve traffic? Checked
        dependencies are the ones every request in this phase needs."""
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await get_redis_client().ping()
        return {"status": "ready"}

    @app.get("/metrics", tags=["Observability"])
    async def metrics() -> Response:
        depth = await cast(Awaitable[int], get_redis_client().llen(ARQ_QUEUE_NAME))
        queue_length.set(depth)
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    prefix = settings.api_v1_prefix
    for router in (
        auth_router,
        auth_users_router,
        roles_router,
        users_admin_router,
        audit_router,
        documents_router,
        processing_jobs_router,
        extraction_router,
        extraction_runs_router,
        extraction_tables_router,
        trust_runs_router,
        trust_pipeline_runs_router,
        trust_entities_router,
        trust_review_queue_router,
        graph_router,
        graph_nodes_router,
        graph_edges_router,
        graph_entity_router,
        graph_relationships_router,
    ):
        app.include_router(router, prefix=prefix)

    return app


app = create_app()
