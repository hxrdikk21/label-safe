"""
Unit tests for Cross-Encoder Reranker.
Validates two-stage candidate scoring, threshold cutoffs, and entity prioritization.
"""

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.rag.reranker import CrossEncoderReranker


def test_cross_encoder_reranking_accuracy():
    """Verify that a passage with high semantic overlap is reranked above a low-overlap passage."""
    reranker = CrossEncoderReranker(score_threshold=0.10)

    p_relevant = EvidencePassage(
        passage_id="PASS-REL",
        document_id="DOC-1",
        rxcui="136443",
        loinc_section_code="34070-3",
        section_title="Contraindications",
        passage_index=0,
        content="Sildenafil coadministration with organic nitrates causes severe hypotension.",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    p_marginal = EvidencePassage(
        passage_id="PASS-MARG",
        document_id="DOC-2",
        rxcui="136443",
        loinc_section_code="34076-9",
        section_title="Overdosage",
        passage_index=0,
        content="In cases of overdose standard supportive measures should be adopted as required.",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    query = "sildenafil nitrates severe hypotension interaction"
    # Pass in marginal first, relevant second
    results = reranker.rerank(query=query, passages=[p_marginal, p_relevant], top_k=2)

    assert len(results) == 2
    # Relevant passage should be promoted to rank 1
    assert results[0].passage.passage_id == "PASS-REL"
    assert results[0].final_rank == 1
    assert results[0].rerank_score > results[1].rerank_score


def test_cross_encoder_threshold_filtering():
    """Verify that passages below the relevance threshold are pruned."""
    reranker = CrossEncoderReranker(score_threshold=0.70)

    p_unrelated = EvidencePassage(
        passage_id="PASS-UNRELATED",
        document_id="DOC-99",
        rxcui="999",
        loinc_section_code="000",
        section_title="Storage",
        passage_index=0,
        content="Store at room temperature 20C to 25C away from excessive moisture.",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    results = reranker.rerank(query="warfarin bleeding with ibuprofen", passages=[p_unrelated])
    assert len(results) == 0
