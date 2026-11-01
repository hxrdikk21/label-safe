"""respx helpers that emulate the RxNav REST endpoints used by the normalizer."""

import httpx
import respx

from src.labelsafe.ingestion.rxnav import DEFAULT_BASE_URL as BASE


def mock_name(name: str, rxcuis: list[str]) -> respx.Route:
    id_group = {"rxnormId": rxcuis} if rxcuis else {}
    return respx.get(f"{BASE}/rxcui.json", params={"name": name}).respond(200, json={"idGroup": id_group})


def mock_approximate(term: str, rxcuis: list[str]) -> respx.Route:
    candidates = [{"rxcui": r, "score": "8.0", "rank": str(i + 1)} for i, r in enumerate(rxcuis)]
    return respx.get(f"{BASE}/approximateTerm.json", params={"term": term}).respond(
        200, json={"approximateGroup": {"candidate": candidates}}
    )


def mock_properties(rxcui: str, name: str, tty: str) -> respx.Route:
    return respx.get(f"{BASE}/rxcui/{rxcui}/properties.json").respond(
        200, json={"properties": {"rxcui": rxcui, "name": name, "tty": tty}}
    )


def mock_missing_properties(rxcui: str) -> respx.Route:
    return respx.get(f"{BASE}/rxcui/{rxcui}/properties.json").respond(200, json={})


def mock_related(rxcui: str, groups: dict[str, list[tuple[str, str]]]) -> respx.Route:
    concept_groups = [
        {"tty": tty, "conceptProperties": [{"rxcui": r, "name": n, "tty": tty} for r, n in members]}
        if members
        else {"tty": tty}
        for tty, members in groups.items()
    ]
    return respx.get(f"{BASE}/rxcui/{rxcui}/related.json").respond(
        200, json={"relatedGroup": {"rxcui": None, "conceptGroup": concept_groups}}
    )


def mock_unii(rxcui: str, unii: str | None) -> respx.Route:
    body = (
        {
            "propConceptGroup": {
                "propConcept": [{"propCategory": "CODES", "propName": "UNII_CODE", "propValue": unii}]
            }
        }
        if unii
        else {}
    )
    return respx.get(f"{BASE}/rxcui/{rxcui}/property.json").respond(200, json=body)


def mock_atorvastatin() -> None:
    """Lipitor (BN 153165) -> atorvastatin (IN 83367, UNII A0JWA85V8F)."""
    mock_name("Lipitor", ["153165"])
    mock_name("atorvastatin", ["83367"])
    mock_properties("153165", "Lipitor", "BN")
    mock_properties("83367", "atorvastatin", "IN")
    mock_related("153165", {"IN": [("83367", "atorvastatin")], "MIN": []})
    mock_related(
        "83367",
        {
            "PIN": [
                ("83366", "atorvastatin calcium"),
                ("1297766", "atorvastatin calcium trihydrate"),
            ],
            "SCD": [
                ("617312", "atorvastatin 10 MG Oral Tablet"),
                ("597977", "amlodipine 5 MG / atorvastatin 10 MG Oral Tablet"),
            ],
            "SBD": [
                ("617314", "atorvastatin 10 MG Oral Tablet [Lipitor]"),
                ("597999", "amlodipine 5 MG / atorvastatin 10 MG Oral Tablet [Caduet]"),
            ],
        },
    )
    mock_unii("83367", "A0JWA85V8F")


def unavailable(rxcui_path: str) -> respx.Route:
    return respx.get(f"{BASE}/{rxcui_path}").mock(return_value=httpx.Response(503))
