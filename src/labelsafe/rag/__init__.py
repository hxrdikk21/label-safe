"""
RAG package: the RagService pipeline (retriever -> reranker -> CRAG gate -> generator -> citations).
"""

from src.labelsafe.rag.generator import ContextBuilder, FormattedContext
from src.labelsafe.rag.retriever import InMemoryRetriever, PostgresRetriever, Retriever
from src.labelsafe.rag.service import RagService

__all__ = [
    "ContextBuilder",
    "FormattedContext",
    "InMemoryRetriever",
    "PostgresRetriever",
    "RagService",
    "Retriever",
]
