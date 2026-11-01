"""RxNav client and MedicationNormalizer entity-resolution tests (HTTP mocked with respx)."""

import httpx
import pytest
import respx

from src.labelsafe.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.labelsafe.ingestion.http import RetryPolicy
from src.labelsafe.ingestion.rxnav import DEFAULT_BASE_URL, RxConcept, RxNavClient
from src.labelsafe.knowledge.normalizer import (
    MedicationNormalizer,
    MedicationNotFoundError,
    marketed_salt_forms,
    single_ingredient_brands,
)
from tests.unit.rxnav_mocks import (
    mock_approximate,
    mock_atorvastatin,
    mock_missing_properties,
    mock_name,
    mock_properties,
    mock_related,
    mock_unii,
)


@pytest.fixture
def normalizer(http_client: httpx.AsyncClient, no_wait_policy: RetryPolicy) -> MedicationNormalizer:
    return MedicationNormalizer(RxNavClient(http_client, retry_policy=no_wait_policy))


class TestNormalizer:
    @respx.mock
    async def test_rxnav_normalizer_resolves_brand_to_ingredient(
        self, normalizer: MedicationNormalizer
    ) -> None:
        mock_atorvastatin()
        concept = await normalizer.normalize("  Lipitor ")
        assert concept.rxcui == "83367"
        assert concept.canonical_name == "atorvastatin"
        assert concept.term_type == "IN"
        assert [(i.unii, i.name, i.is_active) for i in concept.ingredients] == [
            ("A0JWA85V8F", "atorvastatin", True)
        ]
        assert concept.synonyms == ["Lipitor"]
        assert concept.is_ambiguous is False
        assert concept.ambiguity_candidates == []

    @respx.mock
    async def test_hydrate_salts_and_combination_brands_do_not_pollute(
        self, normalizer: MedicationNormalizer
    ) -> None:
        mock_atorvastatin()
        concept = await normalizer.normalize("atorvastatin")
        assert concept.rxcui == "83367"
        assert concept.is_ambiguous is False  # salts never appear in marketed SCD names
        assert "Caduet" not in concept.synonyms
        assert concept.synonyms == ["Lipitor"]

    @respx.mock
    async def test_bare_ingredient_with_distinct_marketed_salts_is_ambiguous(
        self, normalizer: MedicationNormalizer
    ) -> None:
        mock_name("metoprolol", ["6918"])
        mock_properties("6918", "metoprolol", "IN")
        mock_related(
            "6918",
            {
                "PIN": [
                    ("102313", "metoprolol fumarate"),
                    ("203191", "metoprolol tartrate"),
                    ("221124", "metoprolol succinate"),
                ],
                "SCD": [
                    ("866514", "metoprolol tartrate 50 MG Oral Tablet"),
                    ("866436", "24 HR metoprolol succinate 50 MG Extended Release Oral Tablet"),
                    ("866479", "hydrochlorothiazide 25 MG / metoprolol tartrate 100 MG Oral Tablet"),
                ],
                "SBD": [("866516", "metoprolol tartrate 50 MG Oral Tablet [Lopressor]")],
            },
        )
        mock_unii("6918", "GEB06NHM23")
        concept = await normalizer.normalize("metoprolol")
        assert concept.rxcui == "6918"
        assert concept.is_ambiguous is True
        assert concept.ambiguity_candidates == ["203191", "221124"]
        assert concept.synonyms == ["Lopressor"]

    @respx.mock
    async def test_salt_form_query_keeps_precise_salt(self, normalizer: MedicationNormalizer) -> None:
        mock_name("metoprolol succinate", ["221124"])
        mock_properties("221124", "metoprolol succinate", "PIN")
        mock_related(
            "221124",
            {
                "IN": [("6918", "metoprolol")],
                "SBD": [("866438", "24 HR metoprolol succinate 50 MG Extended Release Oral Tablet [Toprol]")],
            },
        )
        mock_unii("6918", "GEB06NHM23")
        concept = await normalizer.normalize("metoprolol succinate")
        assert (concept.rxcui, concept.term_type, concept.is_ambiguous) == ("221124", "PIN", False)
        assert [i.name for i in concept.ingredients] == ["metoprolol"]
        assert concept.synonyms == ["Toprol"]

    @respx.mock
    async def test_multi_ingredient_brand_decomposes(self, normalizer: MedicationNormalizer) -> None:
        mock_name("Augmentin", ["151392"])
        mock_properties("151392", "Augmentin", "BN")
        mock_related(
            "151392",
            {
                "IN": [("723", "amoxicillin"), ("48203", "clavulanate")],
                "MIN": [("19711", "amoxicillin / clavulanate")],
            },
        )
        mock_unii("723", "804826J2HU")
        mock_unii("48203", None)
        concept = await normalizer.normalize("Augmentin")
        assert (concept.rxcui, concept.term_type) == ("19711", "MIN")
        assert concept.canonical_name == "amoxicillin / clavulanate"
        assert [(i.name, i.unii) for i in concept.ingredients] == [
            ("amoxicillin", "804826J2HU"),
            ("clavulanate", "RXCUI:48203"),  # explicit, non-UNII fallback when RxNorm has no UNII
        ]
        assert concept.synonyms == ["Augmentin"]

    @respx.mock
    async def test_multiple_min_concept_lists_brands(self, normalizer: MedicationNormalizer) -> None:
        mock_name("amoxicillin / clavulanate", ["19711"])
        mock_properties("19711", "amoxicillin / clavulanate", "MIN")
        mock_related(
            "19711", {"IN": [("723", "amoxicillin")], "BN": [("151392", "Augmentin"), ("1", "Amoclan")]}
        )
        mock_unii("723", "804826J2HU")
        concept = await normalizer.normalize("amoxicillin / clavulanate")
        assert concept.term_type == "MIN"
        assert concept.synonyms == ["Amoclan", "Augmentin"]

    @respx.mock
    async def test_brand_without_single_min_stays_on_brand(self, normalizer: MedicationNormalizer) -> None:
        mock_name("ComboBrand", ["900"])
        mock_properties("900", "ComboBrand", "BN")
        mock_related("900", {"IN": [("1", "drug a"), ("2", "drug b")], "MIN": []})
        mock_unii("1", "UNIIA")
        mock_unii("2", "UNIIB")
        concept = await normalizer.normalize("ComboBrand")
        assert (concept.rxcui, concept.term_type) == ("900", "BN")
        assert [i.unii for i in concept.ingredients] == ["UNIIA", "UNIIB"]

    @respx.mock
    async def test_query_matching_distinct_concepts_is_ambiguous(
        self, normalizer: MedicationNormalizer
    ) -> None:
        mock_name("Brandx", ["10", "20", "30"])
        mock_properties("10", "drug ten", "IN")
        mock_properties("20", "drug twenty", "IN")
        mock_missing_properties("30")  # retired concept is skipped
        mock_related("10", {"PIN": [], "SCD": [], "SBD": []})
        mock_related("20", {"PIN": [], "SCD": [], "SBD": []})
        mock_unii("10", "U10")
        concept = await normalizer.normalize("Brandx")
        assert concept.rxcui == "10"
        assert concept.is_ambiguous is True
        assert concept.ambiguity_candidates == ["10", "20"]

    @respx.mock
    async def test_approximate_match_is_always_flagged(self, normalizer: MedicationNormalizer) -> None:
        mock_atorvastatin()
        mock_name("lipitr", [])
        mock_approximate("lipitr", ["153165", "153165"])
        concept = await normalizer.normalize("lipitr")
        assert concept.rxcui == "83367"
        assert concept.is_ambiguous is True
        assert concept.ambiguity_candidates == ["83367"]
        assert "lipitr" not in concept.synonyms

    @respx.mock
    async def test_unknown_drug_raises_not_found(self, normalizer: MedicationNormalizer) -> None:
        mock_name("xyzzyq", [])
        respx.get(f"{DEFAULT_BASE_URL}/approximateTerm.json").respond(200, json={"approximateGroup": {}})
        with pytest.raises(MedicationNotFoundError):
            await normalizer.normalize("xyzzyq")

    @respx.mock
    async def test_approximate_matching_can_be_disabled(self, http_client: httpx.AsyncClient) -> None:
        mock_name("lipitr", [])
        approx = respx.get(f"{DEFAULT_BASE_URL}/approximateTerm.json")
        with pytest.raises(MedicationNotFoundError):
            await MedicationNormalizer(RxNavClient(http_client), allow_approximate=False).normalize("lipitr")
        assert approx.call_count == 0

    @respx.mock
    async def test_only_retired_candidates_is_not_found(self, normalizer: MedicationNormalizer) -> None:
        mock_name("oldname", ["5"])
        mock_missing_properties("5")
        with pytest.raises(MedicationNotFoundError):
            await normalizer.normalize("oldname")

    @respx.mock
    async def test_outage_is_explicit_failure(self, normalizer: MedicationNormalizer) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/rxcui.json").respond(503)
        with pytest.raises(UpstreamUnavailableError):
            await normalizer.normalize("Lipitor")

    async def test_empty_query_rejected(self, normalizer: MedicationNormalizer) -> None:
        with pytest.raises(ValueError):
            await normalizer.normalize("   ")


class TestHelpers:
    def test_marketed_salt_forms_prefers_longest_match(self) -> None:
        pins = [
            RxConcept("1", "levothyroxine sodium", "PIN"),
            RxConcept("2", "levothyroxine sodium anhydrous", "PIN"),
        ]
        scds = [
            RxConcept("10", "levothyroxine sodium 0.1 MG Oral Tablet", "SCD"),
            RxConcept("11", "levothyroxine sodium anhydrous 0.05 MG Oral Tablet", "SCD"),
            RxConcept("12", "levothyroxine sodium 0.2 MG Oral Tablet", "SCD"),
        ]
        assert marketed_salt_forms(pins, scds) == ["1", "2"]
        assert marketed_salt_forms(pins, scds[:1]) == ["1"]

    def test_single_ingredient_brands(self) -> None:
        sbds = [
            RxConcept("1", "drug 10 MG Oral Tablet [Zeta]", "SBD"),
            RxConcept("2", "drug 20 MG Oral Tablet [Alpha]", "SBD"),
            RxConcept("3", "a 1 MG / drug 2 MG Oral Tablet [Combo]", "SBD"),
            RxConcept("4", "drug 5 MG Oral Tablet", "SBD"),
        ]
        assert single_ingredient_brands(sbds) == ["Alpha", "Zeta"]


class TestRxNavClient:
    @respx.mock
    async def test_get_unii_absent(self, http_client: httpx.AsyncClient) -> None:
        mock_unii("1", None)
        assert await RxNavClient(http_client).get_unii("1") is None

    @respx.mock
    async def test_get_unii_404_is_none(self, http_client: httpx.AsyncClient) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/rxcui/1/property.json").respond(404)
        assert await RxNavClient(http_client).get_unii("1") is None

    @respx.mock
    async def test_non_json_payload(self, http_client: httpx.AsyncClient) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/rxcui/1/properties.json").respond(200, text="<html>")
        with pytest.raises(UpstreamUnavailableError):
            await RxNavClient(http_client).get_properties("1")

    @respx.mock
    async def test_non_object_payload(self, http_client: httpx.AsyncClient) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/rxcui/1/properties.json").respond(200, json=[1, 2])
        with pytest.raises(UpstreamUnavailableError):
            await RxNavClient(http_client).get_properties("1")

    @respx.mock
    async def test_approximate_without_candidates(self, http_client: httpx.AsyncClient) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/approximateTerm.json").respond(200, json={})
        with pytest.raises(UpstreamNotFoundError):
            await RxNavClient(http_client).approximate_rxcuis("zz")

    @respx.mock
    async def test_find_rxcuis_sends_normalized_search(self, http_client: httpx.AsyncClient) -> None:
        route = mock_name("Lipitor", ["153165"])
        assert await RxNavClient(http_client, base_url=DEFAULT_BASE_URL + "/").find_rxcuis("Lipitor") == [
            "153165"
        ]
        assert route.calls.last.request.url.params["search"] == "2"
