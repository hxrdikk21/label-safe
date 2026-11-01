"""
Canonical Pydantic contracts for RxGuard-RAG.
Shared across all four workstreams to guarantee absolute schema consistency.
"""

from .document import SourceDocument
from .evidence import EvidencePassage, SourceEvidence
from .medication import IngredientReference, MedicationConcept
from .product import DrugProduct
from .rag_response import RAGResponse, VerifiedCitation
from .safety import FindingSeverity, FindingStatus, SafetyFinding
from .safety_evidence import SafetyEvidence
from .user_context import UserAllergyRecord, UserConditionRecord, UserContext

__all__ = [
    "DrugProduct",
    "EvidencePassage",
    "FindingSeverity",
    "FindingStatus",
    "IngredientReference",
    "MedicationConcept",
    "RAGResponse",
    "SafetyEvidence",
    "SafetyFinding",
    "SourceDocument",
    "SourceEvidence",
    "UserAllergyRecord",
    "UserConditionRecord",
    "UserContext",
    "VerifiedCitation",
]
