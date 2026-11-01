"""
User data isolation and clinical context access guard.
Guarantees zero cross-user context leakage and sanitizes patient data for LLM grounding.
"""

from typing import Any

from src.labelsafe.core.contracts.user_context import UserContext


class AccessDeniedError(Exception):
    """Raised when an unauthorized user attempts to access a target user's context."""

    pass


class ContextGuard:
    """Security boundary enforcing strict user-specific clinical data isolation."""

    @staticmethod
    def validate_access(requesting_user_id: str, target_user_id: str, roles: list[str]) -> bool:
        """
        Validates authorization between requesting entity and target user context.
        Rule: A user can ONLY access their own clinical context.
        Even administrative roles cannot view unmasked medical profiles without audit approval.
        """
        clean_req = str(requesting_user_id).strip()
        clean_target = str(target_user_id).strip()

        if clean_req == clean_target:
            return True

        # Deny cross-user access
        raise AccessDeniedError(
            f"Cross-user clinical data access forbidden. Requesting '{clean_req}' cannot access target "
            f"'{clean_target}'."
        )

    @staticmethod
    def sanitize_context_for_prompt(context: UserContext) -> dict[str, Any]:
        """
        Sanitizes and extracts clinical context for RAG and chatbot grounding.
        Strips raw account identifiers, passwords, and PII, returning only clinical factors.
        """
        return {
            "active_medications": list(context.active_medications),
            "allergies": [
                {
                    "substance": a.substance_name,
                    "class": a.allergy_class or "Unspecified",
                    "severity": a.severity,
                }
                for a in context.allergies
            ],
            "conditions": [
                {
                    "name": c.condition_name,
                    "code": c.icd10_code or "Unspecified",
                }
                for c in context.conditions
            ],
        }
