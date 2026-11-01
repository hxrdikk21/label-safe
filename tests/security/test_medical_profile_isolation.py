"""
Tests for Phase 5: Personal Medical History and Health Profile Isolation.
Verifies relational provenance for hospitals, doctors, visits, and prescriptions,
as well as strict patient-scoped access control.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from src.labelsafe.api import dependencies
from src.labelsafe.api.main import app
from src.labelsafe.auth.rate_limit import LoginRateLimiter
from src.labelsafe.auth.store import InMemoryAuthStore
from src.labelsafe.users.profile_store import InMemoryProfileStore
from src.labelsafe.users.service import UserService

PASSWORD = "CorrectHorseBattery9!"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    store, limiter = InMemoryAuthStore(), LoginRateLimiter(max_failures=5, window_seconds=60)
    profiles = InMemoryProfileStore(UserService())
    app.dependency_overrides[dependencies.get_auth_store] = lambda: store
    app.dependency_overrides[dependencies.get_login_rate_limiter] = lambda: limiter
    app.dependency_overrides[dependencies.get_profile_store] = lambda: profiles
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def register_and_login(client: TestClient, username: str) -> dict[str, Any]:
    reg = client.post("/api/v1/auth/register", json={"username": username, "password": PASSWORD})
    assert reg.status_code == 201
    login_res = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert login_res.status_code == 200
    return login_res.json()


def test_complete_medical_history_crud_and_provenance(client: TestClient):
    """Verify that hospitals, doctors, visits, and prescriptions are stored and retrieved."""
    tokens = register_and_login(client, "patient_sarah")
    headers = bearer(tokens["access_token"])

    profile_payload = {
        "active_medications": ["Atorvastatin 20mg", "Metformin 500mg"],
        "allergies": [
            {
                "substance_name": "Amoxicillin",
                "allergy_class": "Beta-Lactam",
                "severity": "SEVERE_ANAPHYLAXIS",
            }
        ],
        "conditions": [
            {
                "condition_name": "Type 2 Diabetes Mellitus",
                "icd10_code": "E11.9",
                "diagnosed_date": "2023-05-10",
            }
        ],
        "hospitals": [
            {
                "name": "Mayo Clinic Rochester",
                "department": "Endocrinology",
                "address": "200 1st St SW, Rochester, MN",
                "phone": "+1-507-284-2511",
            }
        ],
        "doctors": [
            {
                "name": "Dr. Robert Vance, MD",
                "specialty": "Endocrinologist",
                "hospital_affiliation": "Mayo Clinic",
                "contact_phone": "+1-507-284-1111",
            }
        ],
        "medical_visits": [
            {
                "visit_date": "2026-02-14",
                "hospital_name": "Mayo Clinic Rochester",
                "doctor_name": "Dr. Robert Vance, MD",
                "reason_for_visit": "Quarterly HbA1c review and metabolic panel",
                "clinical_notes": "Patient reports good compliance with Metformin.",
            }
        ],
        "prescriptions": [
            {
                "medication_name": "Metformin",
                "dosage": "500mg BID",
                "prescribed_by": "Dr. Robert Vance, MD",
                "prescribed_date": "2026-02-14",
                "status": "ACTIVE",
                "instructions": "Take with meals twice daily.",
            }
        ],
    }

    put_res = client.put("/api/v1/users/me/profile", headers=headers, json=profile_payload)
    assert put_res.status_code == 200, put_res.text

    get_res = client.get("/api/v1/users/me/profile", headers=headers)
    assert get_res.status_code == 200
    data = get_res.json()

    assert data["user_id"] == "patient_sarah"
    assert len(data["active_medications"]) == 2
    assert data["allergies"][0]["substance_name"] == "Amoxicillin"
    assert data["conditions"][0]["icd10_code"] == "E11.9"
    assert data["hospitals"][0]["name"] == "Mayo Clinic Rochester"
    assert data["doctors"][0]["name"] == "Dr. Robert Vance, MD"
    assert data["medical_visits"][0]["doctor_name"] == "Dr. Robert Vance, MD"
    assert data["prescriptions"][0]["medication_name"] == "Metformin"


def test_cross_patient_data_isolation(client: TestClient):
    """Verify that Patient A and Patient B cannot read or overwrite each other's medical history."""
    tokens_a = register_and_login(client, "alice_patient")
    tokens_b = register_and_login(client, "bob_patient")

    headers_a = bearer(tokens_a["access_token"])
    headers_b = bearer(tokens_b["access_token"])

    # Alice saves her private medical history
    client.put(
        "/api/v1/users/me/profile",
        headers=headers_a,
        json={
            "active_medications": ["Warfarin"],
            "conditions": [{"condition_name": "Atrial Fibrillation", "icd10_code": "I48.91"}],
        },
    )

    # Bob's profile should initially be clean
    bob_profile = client.get("/api/v1/users/me/profile", headers=headers_b).json()
    assert bob_profile["user_id"] == "bob_patient"
    assert bob_profile["active_medications"] == []
    assert bob_profile["conditions"] == []

    # Bob saves his own profile
    client.put(
        "/api/v1/users/me/profile",
        headers=headers_b,
        json={
            "active_medications": ["Levothyroxine"],
            "conditions": [{"condition_name": "Hypothyroidism", "icd10_code": "E03.9"}],
        },
    )

    # Verify Alice's profile was not affected by Bob
    alice_profile = client.get("/api/v1/users/me/profile", headers=headers_a).json()
    assert alice_profile["user_id"] == "alice_patient"
    assert alice_profile["active_medications"] == ["Warfarin"]
    assert alice_profile["conditions"][0]["icd10_code"] == "I48.91"
