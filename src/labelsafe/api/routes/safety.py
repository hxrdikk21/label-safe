"""
Safety analysis API routes.
Implements POST /api/v1/safety/analyze and POST /api/v1/safety/explain-findings.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.labelsafe.api.dependencies import (
    get_chat_model,
    get_optional_current_user,
    get_profile_store,
    get_rag_service,
    get_safety_engine,
    per_ip_limit,
)
from src.labelsafe.auth.jwt import TokenPayload
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.rag_response import FindingExplanation, RAGResponse
from src.labelsafe.core.contracts.user_context import UserContext
from src.labelsafe.rag.finding_explainer import FindingExplainer
from src.labelsafe.rag.generator import GeminiChat
from src.labelsafe.rag.service import RagService
from src.labelsafe.safety.engine import ClinicalSafetyReport, SafetyEngine
from src.labelsafe.users.context_guard import AccessDeniedError, ContextGuard
from src.labelsafe.users.profile_store import ProfileStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/safety", tags=["Clinical Safety"])


class SafetyAnalyzeRequest(BaseModel):
    medications: list[MedicationConcept] = Field(
        ..., min_length=1, max_length=50, description="List of medications to screen"
    )
    food_items: list[str] | None = Field(
        default=None, max_length=50, description="Optional concurrent dietary/food items"
    )
    user_context: UserContext | None = Field(
        default=None, description="Optional explicit patient clinical context"
    )
    use_saved_profile: bool = Field(
        default=False,
        description="Whether to automatically load authenticated user's clinical profile",
    )
    include_explanation: bool = Field(
        default=False,
        description="Also return a grounded explanation with verified passage citations",
    )
    clinical_question: str | None = Field(
        default=None, max_length=2000, description="Optional question to focus the grounded explanation"
    )


@router.post(
    "/analyze",
    response_model=ClinicalSafetyReport,
    status_code=status.HTTP_200_OK,
    summary="Screen medication regimen for pairwise DDI, DFI, DCI, and allergy risks",
    dependencies=[per_ip_limit("analyze", "rate_limit_analyze_per_minute")],
)
async def analyze_safety(
    request: SafetyAnalyzeRequest,
    current_user: TokenPayload | None = Depends(get_optional_current_user),
    safety_engine: SafetyEngine = Depends(get_safety_engine),
    profiles: ProfileStore = Depends(get_profile_store),
    rag: RagService = Depends(get_rag_service),
) -> ClinicalSafetyReport:
    """
    Executes Layer C Deterministic Safety screening.
    Merges patient context securely if requested and screens DDI, DFI, DCI, and Allergies.
    With ``include_explanation``, adds the RagService grounded explanation (Layer D); the
    deterministic findings are never altered by it.
    """
    effective_context = request.user_context

    if request.use_saved_profile and current_user:
        profile = await profiles.get(current_user.sub)
        if profile:
            # Enforce patient boundary
            try:
                ContextGuard.validate_access(current_user.sub, profile.user_id, current_user.roles)
            except AccessDeniedError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            effective_context = profile

    # Pairwise screening is CPU work; keep it off the event loop.
    report = await run_in_threadpool(
        safety_engine.evaluate,
        medications=request.medications,
        food_items=request.food_items,
        user_context=effective_context,
    )

    if request.include_explanation:
        try:
            explanation = await rag.explain(request.medications, request.clinical_question, report.findings)
        except Exception:
            # The safety findings stand on their own; a failed explanation must not hide them.
            logger.exception("Grounded explanation failed")
            explanation = RAGResponse(
                response_id=f"RESP-{uuid.uuid4().hex[:12]}",
                findings=report.findings,
                grounded_narrative=(
                    "The explanation could not be generated right now. The findings above still apply."
                ),
                evidence_sufficiency_state="INSUFFICIENT",
                missing_data_warnings=["Explanation service error."],
                disclaimer=report.disclaimer,
            )
        report = report.model_copy(update={"grounded_explanation": explanation})
    return report


class FindingExplanations(BaseModel):
    explanations: list[FindingExplanation]


@router.post(
    "/explain-findings",
    response_model=FindingExplanations,
    summary="Explain each safety finding from its own FDA label passages (RAG), with citations",
    dependencies=[per_ip_limit("explain", "rate_limit_explain_per_minute")],
)
async def explain_findings(
    request: SafetyAnalyzeRequest,
    safety_engine: SafetyEngine = Depends(get_safety_engine),
    rag: RagService = Depends(get_rag_service),
    chat: GeminiChat | None = Depends(get_chat_model),
) -> FindingExplanations:
    """Re-runs the rules on the same inputs (findings are never taken from the client), then explains
    each finding from label text. Called by the Check page right after /analyze."""
    report = await run_in_threadpool(
        safety_engine.evaluate,
        medications=request.medications,
        food_items=request.food_items,
        user_context=request.user_context,
    )
    explainer = FindingExplainer(rag, safety_engine.repo, chat)
    return FindingExplanations(explanations=await explainer.explain(report.findings, request.medications))
