"""
Vector Store Package Initialization.
"""

from src.labelsafe.vector_store.embeddings import EmbeddingEngine, EmbeddingResult
from src.labelsafe.vector_store.pgvector_client import ScoredPassage, VectorStoreClient

__all__ = [
    "EmbeddingEngine",
    "EmbeddingResult",
    "ScoredPassage",
    "VectorStoreClient",
]
