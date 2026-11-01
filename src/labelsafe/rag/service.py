"""
RagService: the 6-step evidence explanation pipeline (Layer D).

1. scope to the request's RxCUIs  2. hybrid retrieve  3. rerank  4. CRAG gate (one rewrite)
5. generate  6. deterministic citation check.

The deterministic ``SafetyEngine`` findings are attached unchanged: this layer explains them and
can never change, soften or hide them (ADR-001).
"""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from src.labelsafe.core.config import Settings, get_settings
from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.rag_response import LabelSource, RAGResponse, VerifiedCitation
from src.labelsafe.core.contracts.safety import SafetyFinding
from src.labelsafe.rag.citations import check_citations, label_sources
from src.labelsafe.rag.gate import CRAGGate, GateAction
from src.labelsafe.rag.generator import ContextBuilder, NarrativeGenerator, get_narrative_generator
from src.labelsafe.rag.reranker import CrossEncoderReranker, RerankedPassage, get_reranker
from src.labelsafe.rag.retriever import Retriever

DISCLAIMER = (
    "LabelSafe CDS Advisory: This clinical guidance is synthesized from FDA drug labels. "
    "Clinical decision support only; consult prescribing information and clinical judgement "
    "before administering therapy."
)
ABSTAIN_NARRATIVE = (
    "Insufficient regulatory evidence found to safely answer this inquiry. "
    "Abstaining to prevent clinical misinformation."
)


class RagService:
    def __init__(
        self,
        retriever: Retriever,
        reranker: CrossEncoderReranker | None = None,
        generator: NarrativeGenerator | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = retriever
        # Models load on first use, so the safety endpoint never pays for them unless asked to explain.
        self._reranker = reranker
        self.generator = generator or get_narrative_generator(self.settings)
        _, proceed, rewrite = self.settings.rag_thresholds()
        self.gate = CRAGGate(proceed, rewrite)
        # Room for every reranked passage (each up to ~1500 characters plus its header).
        self.context_builder = ContextBuilder(
            max_passages=self.settings.rerank_top_k, max_characters=1800 * self.settings.rerank_top_k
        )

    @property
    def reranker(self) -> CrossEncoderReranker:
        if self._reranker is None:
            self._reranker = get_reranker()
        return self._reranker

    async def _retrieve(self, query: str, rxcuis: list[str]) -> list[RerankedPassage]:
        candidates = await self.retriever.search(query, rxcuis, self.settings.retrieval_top_k)
        # Cross-encoder inference is CPU-bound; keep it off the event loop.
        return await asyncio.to_thread(
            self.reranker.rerank, query, candidates, top_k=self.settings.rerank_top_k
        )

    async def retrieve_context(
        self, medications: Sequence[MedicationConcept], question: str
    ) -> tuple[list[EvidencePassage], GateAction]:
        """Steps 1-4: retrieve, rerank and gate (with up to ``max_rewrites`` rewrites).
        Returns no passages when the gate abstains."""
        rxcuis = list(dict.fromkeys(m.rxcui for m in medications))
        # The reranker scores passages against the question text: "why is this risky?" names no drug
        # and every passage scores ~0, so the question always carries the medicine names.
        names = [m.canonical_name for m in medications]
        if names and not any(n.lower() in question.lower() for n in names):
            question = f"{' and '.join(names)}: {question}"
        reranked = await self._retrieve(question, rxcuis)
        action = self.gate.evaluate(reranked)
        for _ in range(self.settings.max_rewrites):
            if action != GateAction.REWRITE:
                break
            reranked = await self._retrieve(self.gate.rewrite_query(question), rxcuis)
            action = self.gate.evaluate(reranked)
        if action == GateAction.ABSTAIN or not reranked:
            return [], GateAction.ABSTAIN
        return [r.passage for r in reranked], action

    async def explain(
        self,
        medications: Sequence[MedicationConcept],
        clinical_question: str | None = None,
        findings: Sequence[SafetyFinding] = (),
    ) -> RAGResponse:
        findings = list(findings)
        query = clinical_question or (
            "Clinical safety, interactions and contraindications of "
            + ", ".join(m.canonical_name for m in medications)
        )

        passages, action = await self.retrieve_context(medications, query)
        if not passages:
            return self._response(
                findings,
                ABSTAIN_NARRATIVE,
                [],
                "INSUFFICIENT",
                unresolved=[query],
                warnings=["No high-confidence regulatory label passages matched search criteria."],
            )

        context = self.context_builder.build_context(passages)
        # Generation may call a remote LLM; keep it off the event loop.
        narrative = await asyncio.to_thread(self.generator.generate, query, context, passages, findings)
        verified_text, citations = check_citations(narrative, {p.passage_id for p in passages})
        # Sentences that failed the check are dropped entirely; only their count is reported.
        kept = [c for c in citations if c.verification_status == "VERIFIED"]
        removed = len(citations) - len(kept)

        if not verified_text:
            return self._response(
                findings,
                ABSTAIN_NARRATIVE,
                [],
                "INSUFFICIENT",
                unresolved=[query],
                warnings=["No generated sentence cited a retrieved label passage."],
            )
        state = "SUFFICIENT"
        warnings: list[str] = []
        if action == GateAction.REWRITE:
            state = "PARTIAL"
            warnings.append("Retrieved evidence is only partially relevant after one query rewrite.")
        if removed:
            state = "PARTIAL"
            warnings.append(f"{removed} sentence(s) without a valid citation were removed.")
        names = {m.rxcui: m.canonical_name for m in medications}
        return self._response(
            findings,
            verified_text,
            kept,
            state,
            warnings=warnings,
            sources=label_sources(verified_text, passages, names),
        )

    @staticmethod
    def _response(
        findings: list[SafetyFinding],
        narrative: str,
        citations: list[VerifiedCitation],
        state: str,
        unresolved: list[str] | None = None,
        warnings: list[str] | None = None,
        sources: list[LabelSource] | None = None,
    ) -> RAGResponse:
        return RAGResponse(
            response_id=f"RESP-{uuid.uuid4().hex[:12]}",
            request_timestamp=datetime.now(UTC),
            findings=findings,
            grounded_narrative=narrative,
            verified_citations=citations,
            sources=sources or [],
            unresolved_questions=unresolved or [],
            evidence_sufficiency_state=state,
            missing_data_warnings=warnings or [],
            disclaimer=DISCLAIMER,
        )
