"""
RAG Comparative Evaluation Suite.
Benchmarks two retrieval tiers over the same in-memory corpus:
1. Vector only: dense cosine similarity (``VectorStoreClient``), passages returned verbatim.
2. RagService: hybrid retrieval + cross-encoder rerank + CRAG gate + cited generation.

Evaluates:
- Retrieval Precision@K and Recall@K
- Hallucination Rate
- Citation Verification Rate
- Safe Abstention Accuracy
- Latency (ms)
"""

import re
import time
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.core.contracts.rag_response import VerifiedCitation
from src.rxguard.rag.retriever import InMemoryRetriever
from src.rxguard.rag.service import RagService
from src.rxguard.vector_store.pgvector_client import VectorStoreClient

VECTOR_TIER = "Tier 1: Vector only"
RAG_TIER = "Tier 2: RagService (hybrid + rerank + CRAG)"


class BenchmarkScenario(BaseModel):
    """Clinical evaluation scenario with ground truth relevance labels."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    query: str
    active_medications: list[str] = Field(default_factory=list)
    gold_passage_ids: list[str] = Field(default_factory=list)
    should_abstain: bool = False


class TierMetrics(BaseModel):
    """Aggregated performance metrics for a specific RAG tier."""

    model_config = ConfigDict(extra="forbid")

    tier_name: str
    scenario_count: int
    mean_latency_ms: float
    precision_at_k: float = Field(..., ge=0.0, le=1.0)
    recall_at_k: float = Field(..., ge=0.0, le=1.0)
    hallucination_rate: float = Field(..., ge=0.0, le=1.0)
    citation_verification_rate: float = Field(..., ge=0.0, le=1.0)
    safe_abstention_accuracy: float = Field(..., ge=0.0, le=1.0)


class RAGComparisonReport(BaseModel):
    """Comparative benchmarking report across the RAG tiers."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tiers: dict[str, TierMetrics]
    winner_tier: str
    summary_notes: list[str]


class RAGBenchmarkHarness:
    """Runs every scenario through the vector-only baseline and the full RagService."""

    def __init__(self, passages: list[EvidencePassage], rag: RagService | None = None):
        self.passages = passages
        self.passage_by_id = {p.passage_id: p for p in passages}
        self.vector_client = VectorStoreClient()
        self.vector_client.insert_batch(passages)
        self.rag = rag or RagService(InMemoryRetriever(passages))

    async def run_benchmarks(self, scenarios: list[BenchmarkScenario], top_k: int = 3) -> RAGComparisonReport:
        metrics_acc: dict[str, dict[str, list[float]]] = {
            t: {
                "latencies": [],
                "precisions": [],
                "recalls": [],
                "hallucinations": [],
                "citations_verified": [],
                "abstentions_correct": [],
            }
            for t in (VECTOR_TIER, RAG_TIER)
        }

        for sc in scenarios:
            t0 = time.perf_counter()
            hits = self.vector_client.search_similar(sc.query, top_k=top_k)
            lat = (time.perf_counter() - t0) * 1000.0
            ids = [h.passage.passage_id for h in hits]
            narrative = " ".join(h.passage.content for h in hits) if hits else "No evidence."
            self._record_trial(metrics_acc[VECTOR_TIER], sc, ids, narrative, lat, not hits)

            # Scenarios name drugs, not RxCUIs: an empty scope searches the whole in-memory corpus.
            t0 = time.perf_counter()
            resp = await self.rag.explain([], clinical_question=sc.query)
            lat = (time.perf_counter() - t0) * 1000.0
            self._record_trial(
                metrics_acc[RAG_TIER],
                sc,
                [c.passage_id for c in resp.verified_citations if c.verification_status == "VERIFIED"],
                resp.grounded_narrative,
                lat,
                resp.evidence_sufficiency_state == "INSUFFICIENT",
                verified_citations=resp.verified_citations,
            )

        n = len(scenarios)

        def mean(values: list[float]) -> float:
            return sum(values) / n if n else 0.0

        tier_results = {
            t: TierMetrics(
                tier_name=t,
                scenario_count=n,
                mean_latency_ms=round(mean(acc["latencies"]), 2),
                precision_at_k=round(mean(acc["precisions"]), 4),
                recall_at_k=round(mean(acc["recalls"]), 4),
                hallucination_rate=round(mean(acc["hallucinations"]), 4),
                citation_verification_rate=round(mean(acc["citations_verified"]), 4),
                safe_abstention_accuracy=round(mean(acc["abstentions_correct"]), 4),
            )
            for t, acc in metrics_acc.items()
        }
        winner = max(
            tier_results,
            key=lambda t: (tier_results[t].safe_abstention_accuracy, tier_results[t].precision_at_k),
        )
        return RAGComparisonReport(
            tiers=tier_results,
            winner_tier=winner,
            summary_notes=[
                "Vector only returns the nearest passages verbatim and never abstains.",
                "RagService abstains when the CRAG gate finds no strong evidence.",
                "RagService keeps only sentences that cite a retrieved passage.",
            ],
        )

    def _record_trial(
        self,
        acc: dict[str, list[float]],
        scenario: BenchmarkScenario,
        retrieved_ids: list[str],
        narrative: str,
        latency_ms: float,
        abstained: bool,
        verified_citations: list[VerifiedCitation] | None = None,
    ) -> None:
        acc["latencies"].append(latency_ms)

        # Safe abstention accuracy
        if scenario.should_abstain:
            acc["abstentions_correct"].append(1.0 if abstained else 0.0)
            acc["precisions"].append(1.0 if abstained else 0.0)
            acc["recalls"].append(1.0 if abstained else 0.0)
            acc["hallucinations"].append(0.0)
            acc["citations_verified"].append(1.0)
            return
        else:
            acc["abstentions_correct"].append(1.0 if not abstained else 0.0)

        # Precision@K and Recall@K against gold passage IDs
        gold_set = set(scenario.gold_passage_ids)
        ret_set = set(retrieved_ids)

        prec = 0.0 if not ret_set else len(ret_set.intersection(gold_set)) / len(ret_set)

        rec = 1.0 if not gold_set else len(ret_set.intersection(gold_set)) / len(gold_set)

        acc["precisions"].append(min(1.0, prec))
        acc["recalls"].append(min(1.0, rec))

        # Hallucination check: sentences lacking supporting evidence
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narrative) if len(s.strip()) > 5]
        if not sentences:
            acc["hallucinations"].append(0.0)
        else:
            # Simple factual overlap against indexed gold passages
            gold_text = " ".join(
                self.passage_by_id[pid].content.lower()
                for pid in scenario.gold_passage_ids
                if pid in self.passage_by_id
            )
            unsupported = 0
            for s in sentences:
                s_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", s.lower()))
                if s_words and not any(w in gold_text for w in s_words):
                    unsupported += 1
            acc["hallucinations"].append(unsupported / len(sentences))

        # Citations verified
        if verified_citations:
            verified_count = sum(1 for c in verified_citations if c.verification_status == "VERIFIED")
            acc["citations_verified"].append(
                verified_count / len(verified_citations) if verified_citations else 1.0
            )
        else:
            acc["citations_verified"].append(1.0 if prec > 0 else 0.0)
