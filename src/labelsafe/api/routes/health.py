"""
Health check and readiness endpoints for LabelSafe API gateway.
"""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from src.labelsafe.api.dependencies import get_session_factory
from src.labelsafe.core.config import get_settings
from src.labelsafe.rag.reranker import get_reranker
from src.labelsafe.safety.rules_db import get_safety_rules_repo
from src.labelsafe.vector_store.embeddings import get_embedding_engine

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]
    timestamp: str


# Set by warm_up() at startup; models load in the background so /health answers immediately.
_models_loaded = False


async def warm_up() -> None:
    """Loads the embedding model and reranker once (real mode) so the first user request isn't
    slowed by it; /ready reports NOT_READY until this finishes."""
    global _models_loaded
    if get_settings().model_mode == "real":
        await asyncio.to_thread(get_embedding_engine)
        await asyncio.to_thread(get_reranker)
    _models_loaded = True


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe: verifies gateway is operational."""
    return HealthResponse(
        status="HEALTHY",
        service="LabelSafe Platform Gateway",
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(response: Response) -> ReadinessResponse:
    """Readiness probe: the rulebook is loaded and, when configured, PostgreSQL answers."""
    checks: dict[str, str] = {}
    try:
        checks["safety_rules_db"] = "ONLINE" if get_safety_rules_repo().stats()["total_rules"] else "EMPTY"
    except RuntimeError:
        checks["safety_rules_db"] = "EMPTY"

    factory = get_session_factory()
    if factory is None:
        checks["database"] = "IN_MEMORY"
    else:
        try:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "ONLINE"
        except Exception:  # any driver/connection error means not ready
            checks["database"] = "OFFLINE"

    if get_settings().model_mode != "real":
        checks["models"] = "FAKE"
    else:
        checks["models"] = "LOADED" if _models_loaded else "LOADING"

    ready = (
        checks["safety_rules_db"] == "ONLINE"
        and checks["database"] != "OFFLINE"
        and checks["models"] != "LOADING"
    )
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="READY" if ready else "NOT_READY",
        checks=checks,
        timestamp=datetime.now(UTC).isoformat(),
    )
