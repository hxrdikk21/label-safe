"""
User clinical profile and authorized context contracts.
Enforces strict medical history representations and isolation boundaries.
"""

from pydantic import BaseModel, ConfigDict, Field


class UserAllergyRecord(BaseModel):
    """User-reported or clinician-verified allergy profile entry."""

    model_config = ConfigDict(extra="forbid")

    allergy_id: str | None = Field(default=None, description="Unique allergy entry UUID")
    substance_name: str = Field(..., min_length=1, description="Allergen name (e.g. Penicillin, Tartrazine)")
    unii: str | None = Field(default=None, description="FDA UNII chemical substance identifier if resolved")
    allergy_class: str | None = Field(default=None, description="Broad class e.g. Beta-Lactam, Sulfonamide")
    severity: str = Field(default="UNKNOWN", description="MILD, MODERATE, SEVERE_ANAPHYLAXIS, UNKNOWN")
    verification_source: str = Field(
        default="USER_REPORTED", description="USER_REPORTED, CLINICIAN_VERIFIED, EHR_IMPORT"
    )


class UserConditionRecord(BaseModel):
    """User pre-existing medical condition or diagnosis."""

    model_config = ConfigDict(extra="forbid")

    condition_id: str | None = Field(default=None, description="Unique condition entry UUID")
    condition_name: str = Field(
        ..., min_length=1, description="Condition description (e.g. Peptic Ulcer Disease)"
    )
    icd10_code: str | None = Field(default=None, description="Standard ICD-10-CM code e.g. K27")
    diagnosed_date: str | None = Field(default=None, description="Date of diagnosis (YYYY-MM-DD)")


class HospitalRecord(BaseModel):
    """User-associated healthcare facility record."""

    model_config = ConfigDict(extra="forbid")

    hospital_id: str | None = Field(default=None, description="Unique hospital UUID")
    name: str = Field(..., min_length=1, description="Hospital or clinic name")
    department: str | None = Field(default=None, description="Primary clinical department")
    address: str | None = Field(default=None, description="Facility address")
    phone: str | None = Field(default=None, description="Facility contact phone number")


class DoctorRecord(BaseModel):
    """User-associated treating physician record."""

    model_config = ConfigDict(extra="forbid")

    doctor_id: str | None = Field(default=None, description="Unique doctor UUID")
    name: str = Field(..., min_length=1, description="Treating physician full name")
    specialty: str | None = Field(default=None, description="Medical specialty (e.g. Cardiology)")
    hospital_affiliation: str | None = Field(default=None, description="Affiliated healthcare institution")
    contact_phone: str | None = Field(default=None, description="Direct clinical contact number")


class MedicalVisitRecord(BaseModel):
    """Clinical encounter or outpatient visit record."""

    model_config = ConfigDict(extra="forbid")

    visit_id: str | None = Field(default=None, description="Unique visit encounter UUID")
    visit_date: str = Field(..., min_length=4, description="Encounter date (YYYY-MM-DD)")
    hospital_name: str = Field(..., min_length=1, description="Encounter facility name")
    doctor_name: str = Field(..., min_length=1, description="Attending physician name")
    reason_for_visit: str = Field(..., min_length=1, description="Chief complaint or diagnosis reason")
    clinical_notes: str | None = Field(default=None, description="Summary clinical encounter notes")


class PrescriptionRecord(BaseModel):
    """Medication prescription order record."""

    model_config = ConfigDict(extra="forbid")

    prescription_id: str | None = Field(default=None, description="Unique prescription UUID")
    medication_name: str = Field(..., min_length=1, description="Prescribed medication name")
    dosage: str | None = Field(default=None, description="Dosage and strength (e.g. 500mg BID)")
    prescribed_by: str = Field(..., min_length=1, description="Prescribing physician name")
    prescribed_date: str = Field(..., min_length=4, description="Date ordered (YYYY-MM-DD)")
    status: str = Field(default="ACTIVE", description="ACTIVE, COMPLETED, DISCONTINUED")
    instructions: str | None = Field(default=None, description="Patient administration instructions")


class UserContext(BaseModel):
    """Authorized clinical profile for an authenticated user session."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., min_length=1, description="Unique user identifier UUID")
    roles: list[str] = Field(
        default_factory=lambda: ["ROLE_USER"], description="RBAC roles: ROLE_USER, ROLE_ADMIN"
    )
    active_medications: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="List of currently active medication names or RxCUIs",
    )
    allergies: list[UserAllergyRecord] = Field(
        default_factory=list, max_length=100, description="Documented allergy history"
    )
    conditions: list[UserConditionRecord] = Field(
        default_factory=list, max_length=100, description="Documented pre-existing medical conditions"
    )
    hospitals: list[HospitalRecord] = Field(
        default_factory=list, description="User associated hospitals and clinics"
    )
    doctors: list[DoctorRecord] = Field(
        default_factory=list, description="User associated treating physicians"
    )
    medical_visits: list[MedicalVisitRecord] = Field(
        default_factory=list, description="Documented medical visits and clinical encounters"
    )
    prescriptions: list[PrescriptionRecord] = Field(
        default_factory=list, description="Documented prescriptions and medication orders"
    )
    emergency_contacts_enabled: bool = Field(
        default=False, description="True if user has configured verified emergency contacts"
    )
