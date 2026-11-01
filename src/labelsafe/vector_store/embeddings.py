"""
Dense Vector Embedding Engine.
Generates normalized dense vector representations for queries and regulatory passages.
Supports deterministic hashed pseudo-embeddings (zero external network dependency)
and standard transformer embeddings (BGE-small / MiniLM-L6 compatible dimension = 384).
"""

import hashlib
import math
import re
import threading
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

# PyTorch inference from several threads at once crashes the process (seen on macOS when parallel
# retrievals embed and rerank together); every model call runs under this one lock.
INFERENCE_LOCK = threading.Lock()


class EmbeddingResult(BaseModel):
    vector: list[float] = Field(..., description="L2-normalized float embedding vector")
    dimension: int
    token_count: int


class EmbeddingEngine:
    """
    Embedding service producing normalized 384-dimensional dense vectors.
    Uses high-entropy feature hashing with n-gram character and token projection,
    strictly normalized so that Cosine Similarity == Dot Product.
    """

    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def embed_text(self, text: str) -> EmbeddingResult:
        """Computes deterministic, unit-normalized dense embedding vector for text."""
        if not text or not text.strip():
            # Return zero vector if empty
            return EmbeddingResult(
                vector=[0.0] * self.dimension,
                dimension=self.dimension,
                token_count=0,
            )

        clean_text = text.lower().strip()
        tokens = re.findall(r"\b[a-zA-Z0-9_\-]+\b", clean_text)
        token_count = len(tokens)

        # Accumulator vector
        vec = [0.0] * self.dimension

        # Feature hashing across word unigrams, bigrams, and character tri-grams
        features: list[str] = list(tokens)
        for i in range(len(tokens) - 1):
            features.append(f"{tokens[i]}_{tokens[i + 1]}")
        # Add character tri-grams for subword / spelling sensitivity
        for i in range(len(clean_text) - 2):
            features.append(clean_text[i : i + 3])

        for feat in features:
            h = hashlib.sha256(feat.encode("utf-8")).digest()
            # Derive bucket index and sign
            idx = int.from_bytes(h[:4], "big") % self.dimension
            sign = 1.0 if (h[4] & 0x01) == 1 else -1.0
            vec[idx] += sign

        # Compute L2 Norm
        l2_norm = math.sqrt(sum(x * x for x in vec))
        norm_vec = [round(x / l2_norm, 6) for x in vec] if l2_norm > 0 else [0.0] * self.dimension

        return EmbeddingResult(
            vector=norm_vec,
            dimension=self.dimension,
            token_count=token_count,
        )

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generates embeddings for a batch of text passages."""
        return [self.embed_text(t) for t in texts]

    @staticmethod
    def cosine_similarity(v1: list[float], v2: list[float]) -> float:
        """Computes cosine similarity between two unit vectors (bounded in [-1.0, 1.0])."""
        if len(v1) != len(v2) or not v1:
            return 0.0
        # For unit-normalized vectors: cosine similarity = dot product
        dot_product = sum(a * b for a, b in zip(v1, v2, strict=True))
        return max(-1.0, min(1.0, dot_product))


class SentenceTransformerEmbeddingEngine(EmbeddingEngine):
    """
    Real dense embeddings via sentence-transformers (default ``BAAI/bge-small-en-v1.5``, 384-d).
    Same interface as the hashed engine; vectors are L2-normalized so cosine == dot product.
    Requires the ``ml`` extra; the model loads once per process.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", model: Any | None = None):
        if model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)
        self._model = model
        self.model_name = model_name
        dimension = model.get_sentence_embedding_dimension()
        if dimension is None:
            raise ValueError(f"Embedding model {model_name!r} does not report a fixed dimension")
        super().__init__(dimension=int(dimension))

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        with INFERENCE_LOCK:
            vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [
            EmbeddingResult(
                vector=[float(x) for x in vector],
                dimension=self.dimension,
                token_count=len(re.findall(r"\b[a-zA-Z0-9_\-]+\b", text.lower())),
            )
            for text, vector in zip(texts, vectors, strict=True)
        ]

    def embed_text(self, text: str) -> EmbeddingResult:
        if not text or not text.strip():
            return EmbeddingResult(vector=[0.0] * self.dimension, dimension=self.dimension, token_count=0)
        return self.embed_batch([text])[0]


@lru_cache
def get_embedding_engine() -> EmbeddingEngine:
    """sentence-transformers for ``MODEL_MODE=real``; the hashed fake for ``fake``."""
    from src.labelsafe.core.config import get_settings

    settings = get_settings()
    if settings.model_mode == "real":
        return SentenceTransformerEmbeddingEngine(settings.embedding_model)
    return EmbeddingEngine(dimension=settings.embedding_dimension)
