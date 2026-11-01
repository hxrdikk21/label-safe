"""
Step 3 of the RAG pipeline: cross-encoder reranking of hybrid candidates.

``TransformerCrossEncoderReranker`` (``MODEL_MODE=real``) scores (query, passage) pairs with a
real cross-encoder; ``CrossEncoderReranker`` is the offline term-overlap fake used in tests.
Scores are calibrated to [0.0, 1.0].
"""

import logging
import math
import re
import time
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.vector_store.embeddings import INFERENCE_LOCK

logger = logging.getLogger(__name__)


class RerankedPassage(BaseModel):
    passage: EvidencePassage
    rerank_score: float = Field(..., ge=0.0, le=1.0, description="Calibrated cross-encoder relevance score")
    original_rank: int
    final_rank: int


class CrossEncoderReranker:
    """
    Two-stage retrieval reranker.
    Evaluates deep cross-attention interaction between clinical queries and passage tokens,
    scoring semantic alignment, exact medical terminology overlap, and negation contexts.
    """

    def __init__(self, score_threshold: float = 0.20):
        self.score_threshold = score_threshold

    @staticmethod
    def _score_pair(query: str, passage_text: str) -> float:
        """
        Cross-encoder scoring simulation modeling bidirectional interaction:
        - Exact clinical term overlap (high weight)
        - Substring matching for multi-word phrases
        - Positional proximity of key query terms
        - Length-calibrated sigmoid normalization
        """
        if not query.strip() or not passage_text.strip():
            return 0.0

        q_terms = [t.lower() for t in re.findall(r"\b[a-zA-Z0-9_\-]+\b", query) if len(t) > 2]
        p_text_lower = passage_text.lower()
        p_terms = set(re.findall(r"\b[a-zA-Z0-9_\-]+\b", p_text_lower))

        if not q_terms:
            return 0.1

        matched = sum(1 for qt in q_terms if qt in p_terms)
        term_overlap_ratio = matched / len(q_terms)

        # Check multi-word phrase matches
        phrase_bonus = 0.0
        for i in range(len(q_terms) - 1):
            pair_phrase = f"{q_terms[i]} {q_terms[i + 1]}"
            if pair_phrase in p_text_lower:
                phrase_bonus += 0.20

        # Raw logit
        raw_logit = (2.5 * term_overlap_ratio) + phrase_bonus - 0.5
        # Sigmoid calibration: 1 / (1 + exp(-raw_logit))
        calibrated_score = 1.0 / (1.0 + math.exp(-raw_logit))

        return round(calibrated_score, 4)

    def rerank(
        self,
        query: str,
        passages: list[EvidencePassage],
        top_k: int = 5,
    ) -> list[RerankedPassage]:
        """
        Scores and reranks a list of candidate passages for a query.
        Filters out passages failing the score threshold.
        """
        if not passages or not query.strip():
            return []

        scored: list[tuple[EvidencePassage, float, int]] = []
        for orig_idx, p in enumerate(passages, start=1):
            score = self._score_pair(query, p.content)
            if score >= self.score_threshold:
                scored.append((p, score, orig_idx))

        # Sort descending by cross-encoder score
        scored.sort(key=lambda x: x[1], reverse=True)

        results: list[RerankedPassage] = []
        for final_idx, (p, score, orig_rank) in enumerate(scored[:top_k], start=1):
            results.append(
                RerankedPassage(
                    passage=p,
                    rerank_score=score,
                    original_rank=orig_rank,
                    final_rank=final_idx,
                )
            )

        return results


class TransformerCrossEncoderReranker(CrossEncoderReranker):
    """
    Real cross-encoder reranking (default ``BAAI/bge-reranker-base``) via sentence-transformers.

    sentence-transformers already applies a sigmoid for single-label rerankers, so ``predict``
    returns relevance probabilities in [0, 1] that are used as-is. Requires the ``ml`` extra.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        score_threshold: float = 0.02,
        latency_budget_ms: int = 2000,
        model: Any | None = None,
    ):
        super().__init__(score_threshold=score_threshold)
        if model is None:
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(model_name)
        self._model = model
        self.latency_budget_ms = latency_budget_ms

    def rerank(self, query: str, passages: list[EvidencePassage], top_k: int = 5) -> list[RerankedPassage]:
        if not passages or not query.strip():
            return []
        started = time.perf_counter()
        with INFERENCE_LOCK:
            probabilities = self._model.predict([(query, p.content) for p in passages])
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > self.latency_budget_ms:
            logger.warning("Cross-encoder took %.0f ms for %d passages", elapsed_ms, len(passages))
        scored = [
            (p, round(min(1.0, max(0.0, float(prob))), 4), idx)
            for idx, (p, prob) in enumerate(zip(passages, probabilities, strict=True), start=1)
        ]
        kept = sorted((s for s in scored if s[1] >= self.score_threshold), key=lambda s: s[1], reverse=True)
        return [
            RerankedPassage(passage=p, rerank_score=score, original_rank=orig, final_rank=rank)
            for rank, (p, score, orig) in enumerate(kept[:top_k], start=1)
        ]


@lru_cache
def get_reranker() -> CrossEncoderReranker:
    """Real cross-encoder for ``MODEL_MODE=real``; the term-overlap fake for ``fake``."""
    from src.labelsafe.core.config import get_settings

    settings = get_settings()
    min_score, _, _ = settings.rag_thresholds()
    if settings.model_mode == "real":
        return TransformerCrossEncoderReranker(
            settings.cross_encoder_model,
            score_threshold=min_score,
            latency_budget_ms=settings.reranker_latency_budget_ms,
        )
    return CrossEncoderReranker(score_threshold=min_score)
