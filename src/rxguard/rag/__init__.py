"""
RAG package: the RagService pipeline (retriever -> reranker -> CRAG gate -> generator -> citations).
"""

from src.rxguard.rag.generator import ContextBuilder, FormattedContext
from src.rxguard.rag.retriever import InMemoryRetriever, PostgresRetriever, Retriever
from src.rxguard.rag.service import RagService

__all__ = [
    "ContextBuilder",
    "FormattedContext",
    "InMemoryRetriever",
    "PostgresRetriever",
    "RagService",
    "Retriever",
]
