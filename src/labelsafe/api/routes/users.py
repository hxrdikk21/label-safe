"""
User clinical profile routes (checklist Task 10.1).
Implements GET/PUT/DELETE /api/v1/users/me/profile.

The profile always belongs to the authenticated caller: the user id comes from
the access token, never from the request body, so one user cannot read or
overwrite another's clinical data.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.labelsafe.api.dependencies import get_current_user, get_profile_store
from src.labelsafe.auth.jwt import TokenPayload
from src.labelsafe.core.contracts.user_context import (
    DoctorRecord,
    HospitalRecord,
    MedicalVisitRecord,
    PrescriptionRecord,
    UserAllergyRecord,
    UserConditionRecord,
    UserContext,
)
from src.labelsafe.users.profile_store import ProfileStore

router = APIRouter(prefix="/users", tags=["User Clinical Profile"])


class ProfileUpdate(BaseModel):
    active_medications: list[str] = Field(default_factory=list, max_length=100)
    allergies: list[UserAllergyRecord] = Field(default_factory=list, max_length=100)
    conditions: list[UserConditionRecord] = Field(default_factory=list, max_length=100)
    hospitals: list[HospitalRecord] = Field(default_factory=list, max_length=50)
    doctors: list[DoctorRecord] = Field(default_factory=list, max_length=50)
    medical_visits: list[MedicalVisitRecord] = Field(default_factory=list, max_length=100)
    prescriptions: list[PrescriptionRecord] = Field(default_factory=list, max_length=100)
    emergency_contacts_enabled: bool = False


@router.get("/me/profile", response_model=UserContext)
async def get_my_profile(
    current_user: TokenPayload = Depends(get_current_user),
    profiles: ProfileStore = Depends(get_profile_store),
) -> UserContext:
    profile = await profiles.get(current_user.sub)
    if profile is None:
        return UserContext(
            user_id=current_user.sub,
            roles=current_user.roles,
            active_medications=[],
            allergies=[],
            conditions=[],
        )
    return profile


@router.put("/me/profile", response_model=UserContext)
async def replace_my_profile(
    update: ProfileUpdate,
    current_user: TokenPayload = Depends(get_current_user),
    profiles: ProfileStore = Depends(get_profile_store),
) -> UserContext:
    context = UserContext(
        user_id=current_user.sub,
        roles=current_user.roles,
        active_medications=[m.strip() for m in update.active_medications if m.strip()],
        allergies=update.allergies,
        conditions=update.conditions,
        hospitals=update.hospitals,
        doctors=update.doctors,
        medical_visits=update.medical_visits,
        prescriptions=update.prescriptions,
        emergency_contacts_enabled=update.emergency_contacts_enabled,
    )
    try:
        return await profiles.save(context)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found") from exc


@router.delete("/me/profile", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_profile(
    current_user: TokenPayload = Depends(get_current_user),
    profiles: ProfileStore = Depends(get_profile_store),
) -> None:
    """Privacy wipe of the caller's stored clinical history."""
    await profiles.delete(current_user.sub)
