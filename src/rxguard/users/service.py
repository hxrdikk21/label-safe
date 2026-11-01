"""
User clinical context service.
Manages user profiles, active medications, allergy histories, and documented conditions.
"""

from src.rxguard.core.contracts.user_context import (
    UserAllergyRecord,
    UserConditionRecord,
    UserContext,
)


class UserService:
    """In-memory clinical profile and context store for authenticated users."""

    def __init__(self) -> None:
        self._users: dict[str, UserContext] = {}

    def get_or_create_user(
        self,
        user_id: str,
        roles: list[str] | None = None,
    ) -> UserContext:
        """Retrieves existing UserContext or creates a new one."""
        uid = str(user_id).strip()
        if uid not in self._users:
            self._users[uid] = UserContext(
                user_id=uid,
                roles=roles or ["ROLE_USER"],
                active_medications=[],
                allergies=[],
                conditions=[],
                emergency_contacts_enabled=False,
            )
        return self._users[uid]

    def get_user_context(self, user_id: str) -> UserContext | None:
        """Retrieves UserContext for a specific user ID."""
        return self._users.get(str(user_id).strip())

    def add_active_medication(self, user_id: str, medication: str) -> UserContext:
        """Adds a medication to the user's active regimen."""
        ctx = self.get_or_create_user(user_id)
        clean_med = medication.strip()
        if clean_med and clean_med not in ctx.active_medications:
            ctx.active_medications.append(clean_med)
        return ctx

    def remove_active_medication(self, user_id: str, medication: str) -> UserContext:
        """Removes a medication from the user's active regimen."""
        ctx = self.get_or_create_user(user_id)
        clean_med = medication.strip()
        if clean_med in ctx.active_medications:
            ctx.active_medications.remove(clean_med)
        return ctx

    def add_allergy_record(self, user_id: str, record: UserAllergyRecord) -> UserContext:
        """Appends an allergy entry to the user's profile."""
        ctx = self.get_or_create_user(user_id)
        ctx.allergies.append(record)
        return ctx

    def add_condition_record(self, user_id: str, record: UserConditionRecord) -> UserContext:
        """Appends a pre-existing medical condition to the user's profile."""
        ctx = self.get_or_create_user(user_id)
        ctx.conditions.append(record)
        return ctx

    def clear_clinical_profile(self, user_id: str) -> bool:
        """GDPR/privacy-compliant wipe of user clinical history."""
        uid = str(user_id).strip()
        if uid in self._users:
            del self._users[uid]
            return True
        return False
