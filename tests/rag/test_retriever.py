"""Retriever protocol: RRF fusion and the in-memory implementation's rxcui scope."""

import hashlib

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.rag.retriever import InMemoryRetriever, rrf


def passage(pid: str, rxcui: str, content: str) -> EvidencePassage:
    return EvidencePassage(
        passage_id=pid,
        document_id=f"DOC-{pid}",
        rxcui=rxcui,
        loinc_section_code="34073-7",
        section_title="Drug Interactions",
        passage_index=0,
        content=content,
        sha256_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


A = passage("A", "11289", "Warfarin interaction with ibuprofen causes fatal gastrointestinal bleeding.")
B = passage("B", "5640", "Ibuprofen administration should avoid oral anticoagulants due to hemorrhagic risk.")
C = passage("C", "11289", "Warfarin tablets should be stored at room temperature.")


def test_rrf_boosts_passages_ranked_by_both_channels() -> None:
    assert [p.passage_id for p in rrf([[A, B, C], [C, A]])] == ["A", "C", "B"]
    assert rrf([]) == []


async def test_in_memory_retriever_is_scoped_by_rxcui() -> None:
    retriever = InMemoryRetriever([A, B, C])
    results = await retriever.search("warfarin ibuprofen bleeding risk", ["11289"], top_k=5)
    assert {p.passage_id for p in results} == {"A", "C"}
    assert results[0].passage_id == "A"
    both = await retriever.search("warfarin ibuprofen bleeding risk", ["11289", "5640"], top_k=1)
    assert len(both) == 1


async def test_in_memory_retriever_handles_empty_inputs() -> None:
    assert await InMemoryRetriever([]).search("warfarin", ["11289"], 5) == []
    assert await InMemoryRetriever([A]).search("   ", ["11289"], 5) == []
