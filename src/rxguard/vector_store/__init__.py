"""
Vector Store Package Initialization.
"""

from src.rxguard.vector_store.embeddings import EmbeddingEngine, EmbeddingResult
from src.rxguard.vector_store.pgvector_client import ScoredPassage, VectorStoreClient

__all__ = [
    "EmbeddingEngine",
    "EmbeddingResult",
    "ScoredPassage",
    "VectorStoreClient",
]
