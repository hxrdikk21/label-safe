"""GET /vocab/*/search and /stats: Check-form suggestions, NLM ICD-10 proxy and offline fallback."""

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from src.rxguard.api.main import app
from src.rxguard.api.routes import vocab

client = TestClient(app)


def search(kind: str, q: str, limit: int = 8) -> list[dict]:
    res = client.get(f"/api/v1/vocab/{kind}/search", params={"q": q, "limit": limit})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture(autouse=True)
def _clear_icd_cache() -> None:
    vocab._icd_cache.clear()


def test_foods_prefix_match_and_rule_flag() -> None:
    hits = search("foods", "grape")
    assert hits[0]["label"] == "grapefruit" and hits[0]["has_rules"] is True


@respx.mock
def test_conditions_come_from_nlm_with_codes() -> None:
    respx.get(vocab.NLM_ICD10_URL).mock(
        return_value=httpx.Response(
            200, json=[2, ["J45.20", "L20.9"], None, [["J45.20", "Mild asthma"], ["L20.9", "Eczema"]]]
        )
    )
    hits = search("conditions", "asth")
    assert [(h["code"], h["label"]) for h in hits] == [("J45.20", "Mild asthma"), ("L20.9", "Eczema")]
    assert hits[0]["has_rules"] is True  # curated J45 rule covers J45.20
    assert hits[1]["has_rules"] is False


@respx.mock
def test_conditions_fall_back_to_rulebook_when_nlm_is_down() -> None:
    respx.get(vocab.NLM_ICD10_URL).mock(side_effect=httpx.ConnectError("offline"))
    hits = search("conditions", "asth")
    assert hits and all(h["has_rules"] for h in hits)
    assert any(h["code"].startswith("J45") for h in hits)


def test_allergens_include_rule_groups_and_catalogue_ingredients() -> None:
    labels = [h["label"].lower() for h in search("allergens", "pen", limit=20)]
    assert any("penicillin" in label for label in labels)


def test_stats_counts_catalogue_and_rules() -> None:
    stats = client.get("/api/v1/stats").json()
    assert stats["medicines"] >= 500
    assert stats["rules"] == sum(stats["rules_by_type"].values()) == sum(stats["rules_by_source"].values())
    assert 0 < stats["medicines_with_rules"] <= stats["medicines"]
