"""
Tests for FastAPI API Gateway routes.
Covers health, auth, safety, evidence, and chat endpoints.
"""

from starlette.testclient import TestClient

from src.labelsafe.api.main import app

client = TestClient(app)


def test_health_and_readiness_endpoints():
    """Verify /health and /ready return 200 OK."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "HEALTHY"
    assert "version" in data

    res_ready = client.get("/api/v1/ready")
    assert res_ready.status_code == 200
    data_ready = res_ready.json()
    assert data_ready["status"] == "READY"
    assert data_ready["checks"]["safety_rules_db"] == "ONLINE"


def test_request_tracing_middleware_headers():
    """Verify X-Request-ID and X-Process-Time-Ms headers are injected by middleware."""
    res = client.get("/")
    assert res.status_code == 200
    assert "x-request-id" in res.headers
    assert "x-process-time-ms" in res.headers


def test_auth_registration_and_login_flow():
    """Test user registration and subsequent JWT token retrieval."""
    username = "clinician_dr_smith"
    password = "SuperSecurePassword123!"

    # 1. Register
    reg_res = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "roles": ["clinician"]},
    )
    assert reg_res.status_code == 201

    # 2. Login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["requires_2fa"] is False

    # 3. Setup 2FA
    token = data["access_token"]
    setup_res = client.post(
        "/api/v1/auth/2fa/setup",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert setup_res.status_code == 200
    setup_data = setup_res.json()
    assert "secret" in setup_data
    assert len(setup_data["backup_codes"]) == 8


def test_safety_analyze_endpoint():
    """Test POST /api/v1/safety/analyze with Warfarin and Ibuprofen (contraindicated interaction)."""
    payload = {
        "medications": [
            {
                "rxcui": "11289",
                "canonical_name": "Warfarin",
                "term_type": "IN",
                "ingredients": [{"unii": "6Q180CYQ3E", "name": "Warfarin", "is_active": True}],
            },
            {
                "rxcui": "5640",
                "canonical_name": "Ibuprofen",
                "term_type": "IN",
                "ingredients": [{"unii": "WK2XYI10QM", "name": "Ibuprofen", "is_active": True}],
            },
        ],
        "food_items": [],
        "user_context": None,
    }

    res = client.post("/api/v1/safety/analyze", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["evaluated_medication_count"] == 2
    assert len(data["findings"]) >= 1
    assert data["highest_severity"] == "CONTRAINDICATED"
    assert "disclaimer" in data


def test_chat_message_endpoint():
    """Test POST /api/v1/chat/message with clinical query."""
    payload = {
        "query": "Can I take sildenafil with nitroglycerin?",
        "medications": [
            {
                "rxcui": "136443",
                "canonical_name": "Sildenafil",
                "term_type": "IN",
                "ingredients": [{"unii": "BW9B0ZE037", "name": "Sildenafil", "is_active": True}],
            },
            {
                "rxcui": "4917",
                "canonical_name": "Nitroglycerin",
                "term_type": "IN",
                "ingredients": [{"unii": "G59M7S0WS3", "name": "Nitroglycerin", "is_active": True}],
            },
        ],
    }

    res = client.post("/api/v1/chat/message", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "reply_narrative" in data
    assert data["safety_report"]["highest_severity"] == "CONTRAINDICATED"
    assert len(data["claims"]) >= 1
    assert data["confidence_score"] > 0.0


def test_readiness_fails_when_database_is_unreachable(monkeypatch) -> None:
    from src.labelsafe.api import dependencies

    dependencies.get_session_factory.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none")
    try:
        res = client.get("/api/v1/ready")
        assert res.status_code == 503
        assert res.json()["checks"]["database"] == "OFFLINE"
    finally:
        dependencies.get_session_factory.cache_clear()
