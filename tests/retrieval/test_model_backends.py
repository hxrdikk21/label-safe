"""
Real-model backends behind the existing interfaces, exercised with fake models
(no downloads): sentence-transformers embeddings, cross-encoder reranking,
and the MODEL_MODE factories.
"""

import hashlib
import time

import pytest

from src.labelsafe.core import config
from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.rag import reranker as rr
from src.labelsafe.vector_store import embeddings as emb
from src.labelsafe.vector_store.pgvector_store import to_pgvector


def passage(pid: str, content: str) -> EvidencePassage:
    return EvidencePassage(
        passage_id=pid,
        document_id="SPL",
        rxcui="11289",
        loinc_section_code="34073-7",
        section_title="Drug Interactions",
        passage_index=0,
        content=content,
        sha256_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


class FakeSentenceModel:
    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(self, texts: list[str], normalize_embeddings: bool) -> list[list[float]]:
        assert normalize_embeddings
        return [[1.0, 0.0, 0.0] if "warfarin" in t.lower() else [0.0, 1.0, 0.0] for t in texts]


def test_sentence_transformer_engine_uses_model_dimension_and_vectors() -> None:
    engine = emb.SentenceTransformerEmbeddingEngine("fake", model=FakeSentenceModel())
    assert engine.dimension == 3 and engine.model_name == "fake"
    result = engine.embed_text("Warfarin bleeding")
    assert result.vector == [1.0, 0.0, 0.0] and result.token_count == 2
    assert engine.embed_text("  ").vector == [0.0, 0.0, 0.0]
    assert engine.embed_batch([]) == []
    assert (
        engine.cosine_similarity(engine.embed_text("warfarin").vector, engine.embed_text("other").vector)
        == 0.0
    )


class FakeCrossEncoder:
    """Like sentence-transformers' CrossEncoder.predict: already sigmoid-ed relevance probabilities."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        time.sleep(self.delay)
        return [0.95 if "bleeding" in text else 0.01 for _, text in pairs]


def test_cross_encoder_uses_model_probabilities_as_is() -> None:
    passages = [passage("A", "unrelated label text"), passage("B", "increases bleeding risk")]
    ranked = rr.TransformerCrossEncoderReranker("fake", model=FakeCrossEncoder()).rerank("bleeding", passages)
    assert [r.passage.passage_id for r in ranked] == ["B"]  # A (0.01) falls below the 0.02 threshold
    assert ranked[0].rerank_score == 0.95 and ranked[0].original_rank == 2  # no second sigmoid
    assert rr.TransformerCrossEncoderReranker("fake", model=FakeCrossEncoder()).rerank(" ", passages) == []


def test_slow_cross_encoder_still_ranks(caplog: pytest.LogCaptureFixture) -> None:
    passages = [passage("A", "unrelated"), passage("B", "bleeding")]
    slow = rr.TransformerCrossEncoderReranker("fake", latency_budget_ms=1, model=FakeCrossEncoder(delay=0.01))
    ranked = slow.rerank("bleeding", passages)
    assert [r.passage.passage_id for r in ranked] == ["B"] and ranked[0].rerank_score == 0.95
    assert "Cross-encoder took" in caplog.text


def test_factories_follow_model_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    factories = (emb.get_embedding_engine, rr.get_reranker)
    for factory in factories:
        factory.cache_clear()
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(model_mode="fake"))
    assert type(emb.get_embedding_engine()) is emb.EmbeddingEngine
    assert type(rr.get_reranker()) is rr.CrossEncoderReranker
    for factory in factories:
        factory.cache_clear()

    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(model_mode="real"))
    monkeypatch.setattr(emb, "SentenceTransformerEmbeddingEngine", lambda name: ("emb", name))
    monkeypatch.setattr(rr, "TransformerCrossEncoderReranker", lambda name, **kw: ("rr", name, kw))
    try:
        assert emb.get_embedding_engine() == ("emb", "BAAI/bge-small-en-v1.5")
    finally:
        emb.get_embedding_engine.cache_clear()
    try:
        assert rr.get_reranker() == (
            "rr",
            "BAAI/bge-reranker-base",
            {"score_threshold": 0.02, "latency_budget_ms": 2000},
        )
    finally:
        for factory in factories:
            factory.cache_clear()


def test_pgvector_text_format() -> None:
    assert to_pgvector([0.5, -1.0, 0.0]) == "[0.5,-1,0]"
