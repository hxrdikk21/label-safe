"""DailyMed SPL parsing and REST client tests (all HTTP mocked with respx)."""

import httpx
import pytest
import respx

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.ingestion.dailymed import (
    DEFAULT_BASE_URL,
    DailyMedClient,
    build_contextual_header,
    pack_blocks,
    pack_with_header,
    parse_spl,
)
from src.rxguard.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.rxguard.ingestion.http import RetryPolicy
from src.rxguard.knowledge.loinc_taxonomy import (
    BOXED_WARNING,
    CONTRAINDICATIONS,
    DRUG_INTERACTIONS,
    INACTIVE_INGREDIENTS,
    WARNINGS_AND_PRECAUTIONS,
    is_target_section,
    section_title,
)

SETID = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"
WARFARIN_RXCUI = "11289"


def _section(passages: list[EvidencePassage], code: str) -> list[EvidencePassage]:
    return [p for p in passages if p.loinc_section_code == code]


class TestSplParser:
    def test_every_passage_starts_with_contextual_header(self, warfarin_spl_xml: str) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI, max_passage_chars=300)
        drug = label.products[0].generic_name if label.products else label.document.title
        for p in label.passages:
            header = build_contextual_header(
                drug, section_title(p.loinc_section_code), p.loinc_section_code, "11289"
            )
            assert p.content.startswith(header)
            assert f"[RXCUI: {WARFARIN_RXCUI}]" in p.content
            assert len(p.content) <= 300 or p.content.count("\n\n") == 0  # whole blocks are never split

    def test_contextual_header_format(self) -> None:
        assert build_contextual_header(" Warfarin ", "Drug Interactions", "34073-7", "11289") == (
            "[DRUG: Warfarin] [SECTION: Drug Interactions] [LOINC: 34073-7] [RXCUI: 11289]\n"
        )

    def test_dailymed_parser_extracts_interactions_and_contraindications(self, warfarin_spl_xml: str) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI)

        interactions = _section(label.passages, DRUG_INTERACTIONS.code)
        contraindications = _section(label.passages, CONTRAINDICATIONS.code)
        assert interactions and contraindications
        assert "increase the risk of hemorrhage" in interactions[0].content
        assert "contraindicated in pregnancy" in contraindications[0].content
        assert contraindications[0].section_title == "CONTRAINDICATIONS"
        assert all(p.rxcui == WARFARIN_RXCUI and p.document_id == SETID for p in label.passages)

    def test_all_target_sections_found_in_document_order(self, warfarin_spl_xml: str) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI)
        assert label.sections_found == [
            BOXED_WARNING.code,
            CONTRAINDICATIONS.code,
            WARNINGS_AND_PRECAUTIONS.code,
            DRUG_INTERACTIONS.code,
            INACTIVE_INGREDIENTS.code,
        ]
        assert label.missing_excipient_data is False

    def test_tables_are_preserved_as_rows(self, warfarin_spl_xml: str) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI)
        text = "\n".join(p.content for p in _section(label.passages, DRUG_INTERACTIONS.code))
        assert "Table 1: Examples of CYP450 Interactions with Warfarin" in text
        assert "| Enzyme | Inhibitors | Inducers |" in text
        assert "| CYP2C9 | amiodarone, fluconazole | rifampin |" in text
        assert "7.1 CYP450 Interactions" in text
        assert "<" not in text

    def test_markup_stripped_and_lists_rendered(self, warfarin_spl_xml: str) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI)
        # Line 0 is the contextual header; the rendered section body follows.
        boxed = _section(label.passages, BOXED_WARNING.code)[0].content.split("\n", 1)[1]
        assert boxed.splitlines() == [
            "- Warfarin can cause major or fatal bleeding.",
            "- Perform regular monitoring of INR in all treated patients.",
        ]
        assert "HIGHLIGHT DUPLICATE" not in boxed
        wp = _section(label.passages, WARNINGS_AND_PRECAUTIONS.code)[0].content.split("\n", 1)[1]
        assert wp.startswith("5.1 Hemorrhage\nWarfarin can cause")

    def test_source_document_provenance(self, warfarin_spl_xml: str) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI)
        doc = label.document
        assert doc.document_id == SETID
        assert doc.source_name == "DailyMed"
        assert doc.version == "7"
        assert doc.effective_date == "2024-03-12"
        assert doc.title == "WARFARIN SODIUM tablet Synthetic Pharma Inc."
        assert len(doc.sha256_hash) == 64
        assert str(doc.source_url).endswith(f"setid={SETID}")

    def test_parsing_is_deterministic(self, warfarin_spl_xml: str) -> None:
        first = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI)
        second = parse_spl(warfarin_spl_xml.encode(), rxcui=WARFARIN_RXCUI)
        assert [(p.passage_id, p.sha256_hash) for p in first.passages] == [
            (p.passage_id, p.sha256_hash) for p in second.passages
        ]
        assert first.document.sha256_hash == second.document.sha256_hash

    def test_product_data_elements(self, warfarin_spl_xml: str) -> None:
        label = parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI)
        [product] = label.products
        assert product.ndc == "99999-0101"
        assert product.brand_name == "Warfarin Sodium"
        assert product.generic_name == "warfarin sodium"
        assert product.dosage_form == "TABLET"
        assert product.route == "ORAL"
        assert product.strength == "5 mg"
        assert product.spl_setid == SETID
        assert product.active_ingredient_uniis == ["5Q7ZVV76EI"]
        assert product.inactive_excipient_uniis == ["EWQ57Q8I5X", "70097M6I30"]
        assert product.marketing_status == "Prescription"
        assert label.inactive_ingredients == [
            ("70097M6I30", "MAGNESIUM STEARATE"),
            ("EWQ57Q8I5X", "LACTOSE MONOHYDRATE"),
        ]

    def test_missing_inactive_ingredient_section_is_flagged(self, warfarin_spl_xml: str) -> None:
        start = warfarin_spl_xml.index('<code code="51727-6"')
        section_start = warfarin_spl_xml.rindex("<component>", 0, start)
        section_end = warfarin_spl_xml.index("</component>", start) + len("</component>")
        stripped = warfarin_spl_xml[:section_start] + warfarin_spl_xml[section_end:]

        label = parse_spl(stripped, rxcui=WARFARIN_RXCUI)
        assert label.missing_excipient_data is True
        assert INACTIVE_INGREDIENTS.code not in label.sections_found

    def test_long_sections_are_split_within_the_limit_keeping_table_rows_whole(
        self, warfarin_spl_xml: str
    ) -> None:
        whole = _section(parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI).passages, DRUG_INTERACTIONS.code)
        rows = [line for p in whole for line in p.content.split("\n") if line.startswith("|")]
        limit = len(whole[0].content.split("]\n")[0]) + 160  # header + a few rows: forces the table to split
        interactions = _section(
            parse_spl(warfarin_spl_xml, rxcui=WARFARIN_RXCUI, max_passage_chars=limit).passages,
            DRUG_INTERACTIONS.code,
        )
        assert [p.passage_index for p in interactions] == list(range(len(interactions)))
        assert len(interactions) > len(whole)
        assert all(len(p.content) <= limit for p in interactions)
        split_lines = {line for p in interactions for line in p.content.split("\n")}
        assert rows and all(row in split_lines for row in rows)  # no table row is cut in half

    def test_otc_document_and_minimal_product(self) -> None:
        xml = f"""<document xmlns="urn:hl7-org:v3">
          <code code="34390-5"/><setId root="{SETID}"/><effectiveTime value="bad"/>
          <subject><manufacturedProduct><manufacturedProduct>
            <code code="11111-222"/><name>Pain Relief</name>
            <ingredient classCode="ACTIB"><quantity><numerator value="500" unit="mg"/>
              <denominator value="5" unit="mL"/></quantity>
              <ingredientSubstance><code code="362O9ITL9D" codeSystem="2.16.840.1.113883.4.9"/>
              </ingredientSubstance></ingredient>
            <ingredient classCode="ACTIB"><quantity><numerator value="1" unit="mg"/>
              <denominator value="1" unit="mL"/></quantity><ingredientSubstance/></ingredient>
            <ingredient classCode="IACT"/>
          </manufacturedProduct></manufacturedProduct>
          <manufacturedProduct><manufacturedProduct><name>No NDC</name>
          </manufacturedProduct></manufacturedProduct>
          </subject></document>"""
        label = parse_spl(xml, rxcui="161")
        assert label.document.version == "1"
        assert label.document.effective_date is None
        assert label.document.title == SETID
        assert label.passages == []
        assert label.missing_excipient_data is True
        [product] = label.products
        assert product.marketing_status == "OTC"
        assert product.strength == "500 mg/5 mL / 1 mg/mL"
        assert product.active_ingredient_uniis == ["362O9ITL9D"]
        assert (product.dosage_form, product.route, product.generic_name) == (
            "UNKNOWN",
            "UNKNOWN",
            "Pain Relief",
        )

    @pytest.mark.parametrize(
        "xml",
        [
            "<document><unclosed>",
            '<document xmlns="urn:hl7-org:v3"><title>no set id</title></document>',
            '<!DOCTYPE d [<!ENTITY x "boom">]><document xmlns="urn:hl7-org:v3">&x;</document>',
        ],
    )
    def test_malformed_or_unsafe_xml_is_rejected(self, xml: str) -> None:
        with pytest.raises(UpstreamUnavailableError):
            parse_spl(xml, rxcui=WARFARIN_RXCUI)

    def test_pack_blocks(self) -> None:
        assert pack_blocks([]) == []
        assert pack_blocks(["aaa", "bbb", "ccc"], max_chars=8) == ["aaa\n\nbbb", "ccc"]
        # An oversized block is split (hard-wrapped here: no line or sentence breaks to split on).
        assert pack_blocks(["x" * 20, "y"], max_chars=5) == ["xxxxx"] * 4 + ["y"]

    def test_oversized_table_is_split_on_rows_without_losing_text(self) -> None:
        rows = [f"| Drug {i} | Increases bleeding risk; monitor INR closely. |" for i in range(120)]
        table = "Table 3: Drugs that Can Increase the Risk of Bleeding\n" + "\n".join(rows)
        assert len(table) > 6000
        header = "[DRUG: Warfarin] [SECTION: DRUG INTERACTIONS]\n"
        passages = pack_with_header([table], header, 1500)
        assert len(passages) > 4
        assert all(len(p) <= 1500 and p.startswith(header) for p in passages)
        body = "\n".join(p[len(header) :] for p in passages)
        assert body.split("\n") == table.split("\n")  # every row kept whole, in order

    def test_loinc_taxonomy_helpers(self) -> None:
        assert is_target_section("34073-7")
        assert not is_target_section("42229-5")
        assert not is_target_section(None)
        assert section_title("34066-1") == "BOXED WARNING"


class TestDailyMedClient:
    @respx.mock
    async def test_fetch_label(self, http_client: httpx.AsyncClient, warfarin_spl_xml: str) -> None:
        route = respx.get(f"{DEFAULT_BASE_URL}/spls/{SETID}.xml").respond(200, text=warfarin_spl_xml)
        label = await DailyMedClient(http_client).fetch_label(SETID, rxcui=WARFARIN_RXCUI)
        assert route.call_count == 1
        assert label.document.document_id == SETID

    @respx.mock
    async def test_search_spls(self, http_client: httpx.AsyncClient) -> None:
        route = respx.get(f"{DEFAULT_BASE_URL}/spls.json").respond(
            200,
            json={
                "data": [
                    {"setid": SETID, "title": "WARFARIN", "spl_version": 7, "published_date": "Mar 12, 2024"}
                ]
            },
        )
        [hit] = await DailyMedClient(http_client).search_spls(drug_name="warfarin", rxcui=WARFARIN_RXCUI)
        assert (hit.setid, hit.spl_version) == (SETID, 7)
        assert route.calls.last.request.url.params["drug_name"] == "warfarin"
        assert route.calls.last.request.url.params["rxcui"] == WARFARIN_RXCUI

    @respx.mock
    async def test_search_without_results_is_not_found(self, http_client: httpx.AsyncClient) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/spls.json").respond(200, json={"data": []})
        with pytest.raises(UpstreamNotFoundError):
            await DailyMedClient(http_client).search_spls(drug_name="notadrug")

    @respx.mock
    async def test_search_malformed_payload(self, http_client: httpx.AsyncClient) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/spls.json").respond(200, json={"data": [{"title": "missing setid"}]})
        with pytest.raises(UpstreamUnavailableError):
            await DailyMedClient(http_client).search_spls(rxcui="1")

    async def test_search_requires_a_criterion(self, http_client: httpx.AsyncClient) -> None:
        with pytest.raises(ValueError, match="required"):
            await DailyMedClient(http_client).search_spls()

    @respx.mock
    async def test_missing_label_is_not_found(self, http_client: httpx.AsyncClient) -> None:
        respx.get(f"{DEFAULT_BASE_URL}/spls/{SETID}.xml").respond(404)
        with pytest.raises(UpstreamNotFoundError):
            await DailyMedClient(http_client).fetch_spl_xml(SETID)

    @respx.mock
    async def test_transient_errors_are_retried(
        self, http_client: httpx.AsyncClient, warfarin_spl_xml: str
    ) -> None:
        sleeps: list[float] = []

        async def record(seconds: float) -> None:
            sleeps.append(seconds)

        route = respx.get(f"{DEFAULT_BASE_URL}/spls/{SETID}.xml").mock(
            side_effect=[
                httpx.ConnectTimeout("t"),
                httpx.Response(503),
                httpx.Response(200, text=warfarin_spl_xml),
            ]
        )
        client = DailyMedClient(
            http_client, retry_policy=RetryPolicy(max_attempts=3, base_delay=1.0), sleep=record
        )
        assert await client.fetch_spl_xml(SETID) == warfarin_spl_xml
        assert route.call_count == 3
        assert sleeps == [1.0, 2.0]

    @respx.mock
    async def test_non_retryable_status_fails_fast(self, http_client: httpx.AsyncClient) -> None:
        route = respx.get(f"{DEFAULT_BASE_URL}/spls/{SETID}.xml").respond(403)
        with pytest.raises(UpstreamUnavailableError, match="HTTP 403"):
            await DailyMedClient(http_client).fetch_spl_xml(SETID)
        assert route.call_count == 1
