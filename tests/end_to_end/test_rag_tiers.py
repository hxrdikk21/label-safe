"""
End-to-end comparative evaluation of the two RAG tiers (vector only vs RagService).
Validates latency, retrieval precision/recall, citation verification, and safe abstention.
"""

import pytest

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.evaluation.rag_benchmarks import (
    RAG_TIER,
    VECTOR_TIER,
    BenchmarkScenario,
    RAGBenchmarkHarness,
    RAGComparisonReport,
)


@pytest.fixture
def benchmark_corpus():
    dummy_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    return [
        EvidencePassage(
            passage_id="PASS-WARFARIN-01",
            document_id="DOC-WARFARIN",
            rxcui="11289",
            loinc_section_code="34073-7",
            section_title="Drug Interactions",
            passage_index=0,
            content=(
                "Concomitant administration of Warfarin and Amiodarone causes significant elevation of "
                "PT/INR and increases major bleeding complications."
            ),
            sha256_hash=dummy_hash,
        ),
        EvidencePassage(
            passage_id="PASS-METFORMIN-01",
            document_id="DOC-METFORMIN",
            rxcui="6809",
            loinc_section_code="34070-3",
            section_title="Contraindications",
            passage_index=0,
            content=(
                "Metformin hydrochloride is contraindicated in severe renal impairment due to lactic "
                "acidosis risk."
            ),
            sha256_hash=dummy_hash,
        ),
        EvidencePassage(
            passage_id="PASS-ASPIRIN-01",
            document_id="DOC-ASPIRIN",
            rxcui="1191",
            loinc_section_code="34073-7",
            section_title="Drug Interactions",
            passage_index=0,
            content=(
                "Concomitant administration of Aspirin and Ibuprofen may reduce cardioprotective "
                "antiplatelet effects and elevate GI bleeding."
            ),
            sha256_hash=dummy_hash,
        ),
    ]


@pytest.fixture
def benchmark_scenarios():
    return [
        BenchmarkScenario(
            scenario_id="SCENARIO-DDI-01",
            query="Can patient take Warfarin with Amiodarone together?",
            active_medications=["Warfarin", "Amiodarone"],
            gold_passage_ids=["PASS-WARFARIN-01"],
            should_abstain=False,
        ),
        BenchmarkScenario(
            scenario_id="SCENARIO-CI-01",
            query="Is Metformin safe in severe renal impairment?",
            active_medications=["Metformin"],
            gold_passage_ids=["PASS-METFORMIN-01"],
            should_abstain=False,
        ),
        BenchmarkScenario(
            scenario_id="SCENARIO-DDI-02",
            query="Aspirin and Ibuprofen interaction bleeding risk",
            active_medications=["Aspirin", "Ibuprofen"],
            gold_passage_ids=["PASS-ASPIRIN-01"],
            should_abstain=False,
        ),
        BenchmarkScenario(
            scenario_id="SCENARIO-NEG-01",
            query="Quantum laser resonator semiconductor wavelength calibration",
            active_medications=[],
            gold_passage_ids=[],
            should_abstain=True,
        ),
    ]


async def test_rag_comparative_benchmark_suite(benchmark_corpus, benchmark_scenarios):
    harness = RAGBenchmarkHarness(passages=benchmark_corpus)
    report: RAGComparisonReport = await harness.run_benchmarks(benchmark_scenarios)

    assert set(report.tiers) == {VECTOR_TIER, RAG_TIER}
    for tier_metric in report.tiers.values():
        assert tier_metric.scenario_count == len(benchmark_scenarios)
        assert tier_metric.mean_latency_ms >= 0.0

    rag = report.tiers[RAG_TIER]
    # RagService abstains on the off-topic scenario; vector-only never does.
    assert rag.safe_abstention_accuracy >= 0.75
    assert rag.citation_verification_rate >= 0.75
    assert report.tiers[VECTOR_TIER].safe_abstention_accuracy < 1.0
    assert report.winner_tier == RAG_TIER
    assert len(report.summary_notes) >= 3
