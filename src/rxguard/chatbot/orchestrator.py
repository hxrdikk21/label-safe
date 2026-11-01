"""
The chat on the Check page.

1. Deterministic safety screening of the medications, foods and patient context (never changed, ADR-001).
2. Label passages for the question, searched with the medicine names and earlier questions added
   (a bare "why is this risky?" names no drug, so the reranker would discard every passage).
3. Gemini replies to the conversation, given the findings and passages (PromptManager). Sentences that
   cite a retrieved passage are LABEL claims with a source; the rest are GENERAL information.
4. Without Gemini (LLM_BACKEND=template, or an API failure) the reply is extractive: the findings on the
   first turn plus quoted label text ("offline" mode).
"""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.rxguard.chatbot.prompt_manager import PromptManager
from src.rxguard.core.config import get_settings
from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.core.contracts.medication import MedicationConcept
from src.rxguard.core.contracts.rag_response import LabelSource
from src.rxguard.core.contracts.safety import SafetyFinding
from src.rxguard.core.contracts.user_context import UserContext
from src.rxguard.rag.citations import label_sources, split_sentences, strip_unknown_citations
from src.rxguard.rag.generator import GeminiChat, cite_sentences
from src.rxguard.rag.service import RagService
from src.rxguard.safety.engine import ClinicalSafetyReport, SafetyEngine

KIND = {
    "DRUG_DRUG_INTERACTION": "drug interaction",
    "DRUG_FOOD_INTERACTION": "food interaction",
    "CONTRAINDICATION": "condition contraindication",
    "ALLERGY_EXCIPIENT": "allergy match",
}


class ChatTurn(BaseModel):
    """An earlier exchange in the same conversation, sent back by the client."""

    query: str = Field(..., max_length=2000)
    reply: str = Field(default="", max_length=8000)


class ChatMessageRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000, description="The user's question")
    medications: list[MedicationConcept] | None = Field(
        default_factory=list, max_length=50, description="Medications the question is about"
    )
    food_items: list[str] | None = Field(
        default_factory=list, max_length=50, description="Foods and drinks the question is about"
    )
    user_context: UserContext | None = Field(default=None, description="Conditions and allergies")
    history: list[ChatTurn] = Field(
        default_factory=list, max_length=20, description="Earlier turns of this conversation, oldest first"
    )


class VerifiedClaim(BaseModel):
    """One sentence of the reply and where it comes from."""

    sentence: str
    is_supported: bool
    status: str = Field(
        ...,
        description="LABEL (cites a label passage), GENERAL (uncited), or VERIFIED (offline: rule or quote)",
    )
    best_matching_passage_id: str | None = Field(
        default=None, description="Cited label passage, or the rule id for rulebook findings"
    )
    entailment_confidence: float = Field(..., ge=0.0, le=1.0)
    entailed_evidence_tokens: list[str] = Field(default_factory=list)
    is_contradicted: bool = False


class ChatMessageResponse(BaseModel):
    response_id: str
    query: str
    reply_narrative: str
    mode: Literal["gemini", "offline"] = "offline"
    safety_report: ClinicalSafetyReport
    claims: list[VerifiedClaim]
    sources: list[LabelSource] = Field(default_factory=list)
    unverified_claim_count: int = Field(..., description="Sentences that cite no label (general information)")
    confidence_score: float
    disclaimer: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def retrieval_question(
    query: str,
    history: list[ChatTurn],
    medications: Sequence[MedicationConcept] = (),
    foods: Sequence[str] = (),
) -> str:
    """The question with what it is about: the medicines, foods and the last two earlier questions."""
    subject = " and ".join([m.canonical_name for m in medications] + list(foods))
    question = f"{subject}: {query}" if subject else query
    earlier = [t.query for t in history[-2:]]
    return f"{question} (follow-up to: {' '.join(earlier)})" if earlier else question


_CITATION = re.compile(r"\s*\[([A-Za-z0-9_\-]+)\]")


def annotate(
    reply: str, passages: Sequence[EvidencePassage], names: dict[str, str]
) -> tuple[str, list[VerifiedClaim], list[LabelSource]]:
    """Drops citations of passages that weren't retrieved; labels each sentence LABEL or GENERAL;
    lists the cited passages as sources in order of first citation."""
    by_id = {p.passage_id: p for p in passages}
    text = strip_unknown_citations(reply, by_id)
    claims: list[VerifiedClaim] = []
    for sentence in split_sentences(text):
        ids = [pid for pid in _CITATION.findall(sentence) if pid in by_id]
        claims.append(
            VerifiedClaim(
                sentence=sentence,
                is_supported=bool(ids),
                status="LABEL" if ids else "GENERAL",
                best_matching_passage_id=ids[0] if ids else None,
                entailment_confidence=1.0 if ids else 0.0,
            )
        )
    return text, claims, label_sources(text, passages, names)


def _finding_sentence(f: SafetyFinding) -> str:
    return (
        f"{f.clinical_explanation} This {KIND.get(f.finding_type, 'finding')} is rated "
        f"{f.severity.value.replace('_', ' ').lower()}. What to do: {f.actionable_warning}"
    )


class ChatbotOrchestrator:
    def __init__(
        self, safety_engine: SafetyEngine, rag: RagService | None = None, chat: GeminiChat | None = None
    ) -> None:
        self.safety_engine = safety_engine
        self.rag = rag
        self.chat = chat

    async def generate_response(self, request: ChatMessageRequest) -> ChatMessageResponse:
        medications = request.medications or []
        safety_report = await run_in_threadpool(
            self.safety_engine.evaluate,
            medications=medications,
            food_items=request.food_items or None,
            user_context=request.user_context,
        )
        names = {m.rxcui: m.canonical_name for m in medications}
        passages: list[EvidencePassage] = []
        if self.rag is not None and medications:
            question = retrieval_question(
                request.query, request.history, medications, request.food_items or []
            )
            passages, _ = await self.rag.retrieve_context(medications, question)

        if self.chat is not None:
            system = PromptManager.assemble_system_prompt(
                request.user_context, safety_report.findings, passages, names=names
            )
            history = [(t.query, t.reply) for t in request.history[-6:]]
            text = await run_in_threadpool(
                self.chat.reply, system, history, PromptManager.format_user_query(request.query)
            )
            if text:
                reply, claims, sources = annotate(text, passages, names)
                general = sum(c.status == "GENERAL" for c in claims)
                return ChatMessageResponse(
                    response_id=f"CHAT-RESP-{uuid.uuid4().hex[:8].upper()}",
                    query=request.query,
                    reply_narrative=reply,
                    mode="gemini",
                    safety_report=safety_report,
                    claims=claims,
                    sources=sources,
                    unverified_claim_count=general,
                    confidence_score=0.9 if sources else 0.7,
                    disclaimer=get_settings().clinical_disclaimer,
                )
        return self._offline(request, safety_report, passages, names)

    @staticmethod
    def _offline(
        request: ChatMessageRequest,
        safety_report: ClinicalSafetyReport,
        passages: list[EvidencePassage],
        names: dict[str, str],
    ) -> ChatMessageResponse:
        """No language model: the findings (first turn only) and the top label passages, quoted and cited."""
        parts: list[str] = []
        claims: list[VerifiedClaim] = []
        follow_up = bool(request.history)
        for f in [] if follow_up else safety_report.findings:
            sentence = _finding_sentence(f)
            parts.append(sentence)
            claims.append(
                VerifiedClaim(
                    sentence=sentence,
                    is_supported=True,
                    status="VERIFIED",
                    best_matching_passage_id=f.rule_id,
                    entailment_confidence=1.0,
                )
            )
        if not safety_report.findings and not follow_up:
            parts.append(
                "The rules RxGuard checks found no risk. That does not mean the combination is safe."
            )
        sources: list[LabelSource] = []
        if passages:
            quoted, label_claims, sources = annotate(
                " ".join(cite_sentences(p) for p in passages[:3]), passages, names
            )
            parts.append(quoted)
            claims += label_claims
        else:
            parts.append(
                "The drug labels RxGuard has indexed don't answer this question yet. "
                "Ask your pharmacist or doctor."
            )
        if not follow_up:
            parts += [f"Note: {w}" for w in safety_report.missing_data_warnings]
        return ChatMessageResponse(
            response_id=f"CHAT-RESP-{uuid.uuid4().hex[:8].upper()}",
            query=request.query,
            reply_narrative=" ".join(parts),
            mode="offline",
            safety_report=safety_report,
            claims=claims,
            sources=sources,
            unverified_claim_count=0,  # rulebook facts and quoted label sentences only
            confidence_score=0.8 if passages else 0.6,
            disclaimer=get_settings().clinical_disclaimer,
        )
