"""GET /medications/search: catalog + rule-only drugs, name/brand matching, has_rules flag."""

from starlette.testclient import TestClient

from src.rxguard.api.main import app

client = TestClient(app)


def search(q: str = "", limit: int = 20) -> list[dict]:
    res = client.get("/api/v1/medications/search", params={"q": q, "limit": limit})
    assert res.status_code == 200, res.text
    return res.json()


def test_prefix_match_ranks_exact_drug_first_and_flags_rules() -> None:
    hits = search("warf")
    assert hits[0]["concept"]["rxcui"] == "11289"
    assert hits[0]["has_rules"] is True
    assert hits[0]["concept"]["canonical_name"] == "warfarin"


def test_brand_synonym_finds_generic() -> None:
    assert search("coumadin")[0]["concept"]["rxcui"] == "11289"


def test_rule_only_drug_outside_catalog_is_searchable() -> None:
    [hit] = [h for h in search("sildenafil") if h["concept"]["rxcui"] == "136443"]
    assert hit["has_rules"] is True


def test_catalog_drug_without_rules_is_marked() -> None:
    hits = search("", limit=50)
    assert any(not h["has_rules"] for h in hits)
    flags = [h["has_rules"] for h in hits]
    assert flags == sorted(flags, reverse=True)  # drugs with rules first on an empty query


def test_no_match_and_limit() -> None:
    assert search("zzzz-not-a-drug") == []
    assert len(search("a", limit=3)) == 3
    assert client.get("/api/v1/medications/search", params={"limit": 0}).status_code == 422
