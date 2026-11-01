"""
Regression tests for API paths that crashed before the integration merge:
- GET /api/v1/evidence/subgraph/{id} always returned 500 (missing SafetyEngine.rules_repo).
- use_saved_profile on /safety/analyze and authenticated /chat/message called
  UserService/ContextGuard methods that did not exist.
"""

from typing import Any

import pytest
from starlette.testclient import TestClient

from src.labelsafe.api.dependencies import get_user_service
from src.labelsafe.api.main import app
from src.labelsafe.auth.jwt import create_access_token
from src.labelsafe.core.contracts.user_context import UserAllergyRecord, UserContext
from src.labelsafe.users.service import UserService

client = TestClient(app)

WARFARIN = {"rxcui": "11289", "canonical_name": "Warfarin", "term_type": "IN"}
IBUPROFEN = {"rxcui": "5640", "canonical_name": "Ibuprofen", "term_type": "IN"}


def auth_header(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def test_evidence_subgraph_for_rule_id_returns_graph() -> None:
    res = client.get("/api/v1/evidence/subgraph/RULE-DDI-001")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["finding_id"] == "RULE-DDI-001"
    assert {n["type"] for n in body["nodes"]} >= {"FINDING", "MEDICATION"}


def test_evidence_subgraph_for_finding_emitted_by_analyze() -> None:
    report = client.post("/api/v1/safety/analyze", json={"medications": [WARFARIN, IBUPROFEN]}).json()
    finding_id = report["findings"][0]["finding_id"]
    res = client.get(f"/api/v1/evidence/subgraph/{finding_id}")
    assert res.status_code == 200, res.text
    assert res.json()["finding_id"] == finding_id


def test_evidence_subgraph_unknown_id_is_404_not_500() -> None:
    res = client.get("/api/v1/evidence/subgraph/DOES-NOT-EXIST")
    assert res.status_code == 404


def test_analyze_with_saved_profile_uses_the_callers_context() -> None:
    service: UserService = get_user_service()
    user_id = "patient-saved-profile"
    service.get_or_create_user(user_id)
    service.add_allergy_record(
        user_id,
        UserAllergyRecord(
            substance_name="Penicillin", severity="SEVERE", verification_source="USER_REPORTED"
        ),
    )
    res = client.post(
        "/api/v1/safety/analyze",
        json={"medications": [WARFARIN, IBUPROFEN], "use_saved_profile": True},
        headers=auth_header(user_id),
    )
    assert res.status_code == 200, res.text
    warnings = " ".join(res.json()["missing_data_warnings"])
    assert "allergy history was not supplied" not in warnings  # the saved profile was applied


def test_saved_profile_of_another_user_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    other = UserContext(
        user_id="someone-else", roles=["ROLE_USER"], active_medications=[], allergies=[], conditions=[]
    )

    def leaked_lookup(self: UserService, user_id: str) -> Any:
        return other

    monkeypatch.setattr(UserService, "get_user_context", leaked_lookup)
    res = client.post(
        "/api/v1/safety/analyze",
        json={"medications": [WARFARIN], "use_saved_profile": True},
        headers=auth_header("attacker"),
    )
    assert res.status_code == 403
    res = client.post(
        "/api/v1/chat/message",
        json={"query": "Is warfarin safe?", "medications": [WARFARIN]},
        headers=auth_header("attacker"),
    )
    assert res.status_code == 403


def test_authenticated_chat_loads_saved_profile() -> None:
    service: UserService = get_user_service()
    user_id = "patient-chat-profile"
    service.get_or_create_user(user_id)
    res = client.post(
        "/api/v1/chat/message",
        json={"query": "Can I take warfarin with ibuprofen?", "medications": [WARFARIN, IBUPROFEN]},
        headers=auth_header(user_id),
    )
    assert res.status_code == 200, res.text
    assert res.json()["safety_report"]["highest_severity"] == "CONTRAINDICATED"
