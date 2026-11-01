"""CRAG gate: PROCEED / REWRITE / ABSTAIN routing on the top rerank score, and the one-shot rewrite."""

import hashlib

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.rag.gate import CRAGGate, GateAction
from src.labelsafe.rag.reranker import RerankedPassage

CONTENT = "Warfarin anticoagulant therapy requires regular prothrombin time monitoring."
PASSAGE = EvidencePassage(
    passage_id="PASS-01",
    document_id="DOC-1",
    rxcui="11289",
    loinc_section_code="34073-7",
    section_title="Drug Interactions",
    passage_index=0,
    content=CONTENT,
    sha256_hash=hashlib.sha256(CONTENT.encode()).hexdigest(),
)
GATE = CRAGGate(proceed_score=0.55, rewrite_score=0.40)


def scored(score: float) -> list[RerankedPassage]:
    return [RerankedPassage(passage=PASSAGE, rerank_score=score, original_rank=1, final_rank=1)]


def test_gate_routes_on_top_score() -> None:
    assert GATE.evaluate(scored(0.85)) == GateAction.PROCEED
    assert GATE.evaluate(scored(0.55)) == GateAction.PROCEED
    assert GATE.evaluate(scored(0.54)) == GateAction.REWRITE
    assert GATE.evaluate(scored(0.39)) == GateAction.ABSTAIN


def test_gate_abstains_on_empty_retrieval() -> None:
    assert GATE.evaluate([]) == GateAction.ABSTAIN


def test_rewrite_strips_filler_and_adds_section_focus() -> None:
    rewritten = GATE.rewrite_query("Can I take simvastatin and clarithromycin together?")
    assert rewritten.startswith("simvastatin and clarithromycin")
    assert "Drug Interactions" in rewritten and "contraindications" in rewritten
