"""
Tests for Dense Vector Embedding and pgvector client.
Validates L2 normalization, cosine similarity geometry, metadata filtering, and HNSW DDL generation.
"""

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.vector_store.embeddings import EmbeddingEngine
from src.rxguard.vector_store.pgvector_client import VectorStoreClient


def test_embedding_normalization_and_dimension():
    """Verify that embeddings have unit L2 length and correct dimension."""
    engine = EmbeddingEngine(dimension=384)
    res = engine.embed_text("Warfarin coadministration with NSAIDs increases bleeding risks.")

    assert res.dimension == 384
    assert len(res.vector) == 384
    # Compute L2 norm of result: should be ~1.0
    import math

    norm = math.sqrt(sum(x * x for x in res.vector))
    assert abs(norm - 1.0) < 1e-3


def test_cosine_similarity_symmetry_and_range():
    """Verify that identical text has score 1.0, and dissimilar text has lower score."""
    engine = EmbeddingEngine(dimension=384)
    text1 = "Warfarin and Ibuprofen interaction causing gastrointestinal hemorrhage."
    text2 = "Severe bleeding when warfarin is co-prescribed with NSAIDs."
    text3 = "Oatmeal and fresh apples for a healthy breakfast."

    emb1 = engine.embed_text(text1).vector
    emb2 = engine.embed_text(text2).vector
    emb3 = engine.embed_text(text3).vector

    # Identical score == 1.0
    sim_self = engine.cosine_similarity(emb1, emb1)
    assert abs(sim_self - 1.0) < 1e-4

    # Related medical texts should have high similarity
    sim_related = engine.cosine_similarity(emb1, emb2)
    # Unrelated dietary text should have substantially lower similarity
    sim_unrelated = engine.cosine_similarity(emb1, emb3)

    assert sim_related > sim_unrelated


def test_vector_store_indexing_and_similarity_retrieval():
    """Verify VectorStoreClient indexes passages, filters by RxCUI, and ranks top match."""
    client = VectorStoreClient()

    p1 = EvidencePassage(
        passage_id="PASS-WARFARIN-01",
        document_id="DOC-WARFARIN",
        rxcui="11289",
        loinc_section_code="34073-7",
        section_title="Drug Interactions",
        passage_index=0,
        content=(
            "[DRUG: Warfarin] NSAIDs inhibit platelet aggregation and increase gastrointestinal bleeding "
            "risk."
        ),
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    p2 = EvidencePassage(
        passage_id="PASS-SIMVA-01",
        document_id="DOC-SIMVA",
        rxcui="36567",
        loinc_section_code="34070-3",
        section_title="Contraindications",
        passage_index=0,
        content=(
            "[DRUG: Simvastatin] Strong CYP3A4 inhibitors like clarithromycin significantly increase "
            "statin exposure."
        ),
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    client.insert_batch([p1, p2])
    assert client.count() == 2

    # Query for warfarin bleeding
    results = client.search_similar(query="warfarin bleeding risk with nsaids", top_k=2)
    assert len(results) == 2
    assert results[0].passage.passage_id == "PASS-WARFARIN-01"
    assert results[0].score > results[1].score

    # Filter by RxCUI 36567 (Simvastatin)
    filtered = client.search_similar(query="bleeding risks", filter_rxcui="36567", top_k=2)
    assert len(filtered) == 1
    assert filtered[0].passage.passage_id == "PASS-SIMVA-01"


def test_pgvector_ddl_generation():
    """Verify DDL contains correct HNSW syntax and parameters."""
    client = VectorStoreClient(m=16, ef_construction=64)
    ddl = client.generate_pgvector_ddl()

    assert "CREATE EXTENSION IF NOT EXISTS vector;" in ddl
    assert "USING hnsw (embedding vector_cosine_ops)" in ddl
    assert "WITH (m = 16, ef_construction = 64);" in ddl
