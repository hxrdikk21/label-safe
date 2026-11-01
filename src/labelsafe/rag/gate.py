"""
Step 4 of the RAG pipeline: the Corrective RAG (CRAG) gate.

Judges the reranked evidence before generation, using the top cross-encoder score:
PROCEED (strong evidence), REWRITE (ambiguous: rewrite the query once and retry) or
ABSTAIN (missing evidence is never treated as proof of safety).
"""

import re
from collections.abc import Sequence
from enum import Enum

from src.labelsafe.rag.reranker import RerankedPassage


class GateAction(str, Enum):
    PROCEED = "PROCEED"
    REWRITE = "REWRITE"
    ABSTAIN = "ABSTAIN"


_FILLER = (
    r"^(can i take|is it safe to take|tell me about|what happens if i take)\s+",
    r"\s+(together|at the same time|concurrently)\??$",
)


class CRAGGate:
    def __init__(self, proceed_score: float, rewrite_score: float) -> None:
        self.proceed_score = proceed_score
        self.rewrite_score = rewrite_score

    def evaluate(self, reranked: Sequence[RerankedPassage]) -> GateAction:
        top = max((r.rerank_score for r in reranked), default=0.0)
        if top >= self.proceed_score:
            return GateAction.PROCEED
        if top >= self.rewrite_score:
            return GateAction.REWRITE
        return GateAction.ABSTAIN

    @staticmethod
    def rewrite_query(query: str) -> str:
        """Strips conversational filler and focuses the query on label safety sections."""
        clean = query.strip()
        for pattern in _FILLER:
            clean = re.sub(pattern, "", clean, flags=re.IGNORECASE).strip()
        return f"{clean} Drug Interactions adverse effects contraindications"
