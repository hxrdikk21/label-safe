"""openFDA adapter tests: rate limiting, retries, SHA-256 deduplication and parsing (HTTP mocked)."""

import asyncio
from typing import Any

import httpx
import pytest
import respx

from src.labelsafe.ingestion.errors import UpstreamNotFoundError, UpstreamUnavailableError
from src.labelsafe.ingestion.http import RetryPolicy
from src.labelsafe.ingestion.openfda import (
    DEFAULT_BASE_URL,
    LabelDeduplicator,
    OpenFDAClient,
    SlidingWindowRateLimiter,
    label_fingerprint,
    parse_openfda_label,
)
from src.labelsafe.knowledge.loinc_taxonomy import CONTRAINDICATIONS, DRUG_INTERACTIONS, INACTIVE_INGREDIENTS
from tests.unit.conftest import FakeClock


def make_record(set_id: str = "set-1", record_id: str = "doc-1", **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": record_id,
        "set_id": set_id,
        "version": "3",
        "effective_time": "20250102",
        "drug_interactions": ["7 DRUG INTERACTIONS Strong CYP3A4 inhibitors increase exposure."],
        "contraindications": ["4 CONTRAINDICATIONS Active liver disease."],
        "inactive_ingredient": ["calcium carbonate, hypromellose"],
        "openfda": {
            "brand_name": ["Lipitor"],
            "generic_name": ["ATORVASTATIN CALCIUM"],
            "product_ndc": ["0071-0155", "0071-0156"],
            "route": ["ORAL"],
            "unii": ["48A5M73Z4Q"],
            "product_type": ["HUMAN PRESCRIPTION DRUG"],
        },
    }
    record.update(overrides)
    return record


class TestRateLimiter:
    async def test_openfda_rate_limiter_caps_300_rapid_requests_at_240_per_minute(
        self, fake_clock: FakeClock
    ) -> None:
        limiter = SlidingWindowRateLimiter(240, 60.0, clock=fake_clock, sleep=fake_clock.sleep)
        dispatch_times: list[float] = []

        async def request() -> None:
            await limiter.acquire()
            dispatch_times.append(fake_clock())

        await asyncio.gather(*(request() for _ in range(300)))

        assert len(dispatch_times) == 300
        assert sum(1 for t in dispatch_times if t < 60.0) == 240
        assert min(dispatch_times[240:]) >= 60.0
        for start in dispatch_times:  # no rolling 60s window ever exceeds the quota
            assert sum(1 for t in dispatch_times if start <= t < start + 60.0) <= 240

    async def test_window_slides_and_frees_slots(self, fake_clock: FakeClock) -> None:
        limiter = SlidingWindowRateLimiter(2, 10.0, clock=fake_clock, sleep=fake_clock.sleep)
        await limiter.acquire()
        fake_clock.now = 4.0
        await limiter.acquire()
        await limiter.acquire()  # must wait until the first slot expires at t=10
        assert fake_clock.now == 10.0
        assert fake_clock.sleeps == [6.0]

    @pytest.mark.parametrize(("limit", "period"), [(0, 60.0), (10, 0.0)])
    def test_invalid_configuration(self, limit: int, period: float) -> None:
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(limit, period)


class TestDeduplication:
    def test_rejects_setids_already_sourced_from_dailymed(self) -> None:
        dedup = LabelDeduplicator(dailymed_setids={"set-1"})
        assert dedup.accept(make_record("set-1")) is False
        assert dedup.accept(make_record("set-2")) is True

    def test_rejects_identical_content_fingerprint(self) -> None:
        dedup = LabelDeduplicator()
        assert dedup.accept(make_record(record_id="doc-1")) is True
        # Same label content re-served under a different record id is still a duplicate.
        assert dedup.accept(make_record(record_id="doc-1-mirror", effective_time="20250303")) is False
        assert dedup.accept(make_record(version="4")) is True

    def test_known_fingerprints_from_previous_runs(self) -> None:
        record = make_record()
        dedup = LabelDeduplicator(known_fingerprints=[label_fingerprint(record)])
        assert dedup.accept(record) is False

    def test_fingerprint_is_sha256_and_order_insensitive(self) -> None:
        a = make_record()
        b = dict(reversed(list(make_record().items())))
        assert label_fingerprint(a) == label_fingerprint(b)
        assert len(label_fingerprint(a)) == 64


class TestParsing:
    def test_parse_record_into_contracts(self) -> None:
        parsed = parse_openfda_label(make_record(), rxcui="83367")
        assert parsed.document.document_id == "openfda:doc-1"
        assert parsed.document.source_name == "openFDA"
        assert parsed.document.effective_date == "2025-01-02"
        assert parsed.document.title == "Lipitor (ATORVASTATIN CALCIUM)"
        assert parsed.document.sha256_hash == parsed.fingerprint
        codes = {p.loinc_section_code for p in parsed.passages}
        assert codes == {DRUG_INTERACTIONS.code, CONTRAINDICATIONS.code, INACTIVE_INGREDIENTS.code}
        assert parsed.missing_excipient_data is False
        assert [p.ndc for p in parsed.products] == ["0071-0155", "0071-0156"]
        assert parsed.products[0].active_ingredient_uniis == ["48A5M73Z4Q"]
        assert parsed.products[0].spl_setid == "set-1"
        assert parsed.products[0].marketing_status == "Prescription"

    def test_long_sections_split_on_sentences(self) -> None:
        sentence = "Coadministration with clarithromycin increases exposure. "
        record = make_record(drug_interactions=[sentence * 60])
        parsed = parse_openfda_label(record, rxcui="83367", max_passage_chars=500)
        interactions = [p for p in parsed.passages if p.loinc_section_code == DRUG_INTERACTIONS.code]
        assert len(interactions) > 1
        assert all(len(p.content) <= 500 for p in interactions)
        assert [p.passage_index for p in interactions] == list(range(len(interactions)))

    def test_missing_excipients_and_sparse_metadata(self) -> None:
        record = make_record(
            effective_time=None, openfda={"product_ndc": ["1-2"], "product_type": ["HUMAN OTC DRUG"]}
        )
        del record["inactive_ingredient"]
        parsed = parse_openfda_label(record, rxcui="83367")
        assert parsed.missing_excipient_data is True
        assert parsed.document.effective_date is None
        assert parsed.document.title == "openfda:doc-1"
        [product] = parsed.products
        assert (product.brand_name, product.dosage_form, product.marketing_status) == (
            "1-2",
            "UNKNOWN",
            "OTC",
        )

    def test_record_without_identity_is_rejected(self) -> None:
        with pytest.raises(UpstreamUnavailableError):
            parse_openfda_label(make_record(set_id=""), rxcui="83367")


class TestClient:
    @respx.mock
    async def test_fetch_labels_deduplicates(self, http_client: httpx.AsyncClient) -> None:
        records = [make_record("dm-set"), make_record("set-2", "doc-2"), make_record("set-2", "doc-2-dup")]
        route = respx.get(DEFAULT_BASE_URL).respond(200, json={"meta": {}, "results": records})
        client = OpenFDAClient(http_client, api_key="k3y")
        parsed = await client.fetch_labels_for_generic(
            'atorva"statin', rxcui="83367", deduplicator=LabelDeduplicator(dailymed_setids={"dm-set"})
        )
        assert [p.set_id for p in parsed] == ["set-2"]
        params = route.calls.last.request.url.params
        assert params["search"] == 'openfda.generic_name:"atorvastatin"'
        assert params["api_key"] == "k3y"
        assert params["limit"] == "10"

    @respx.mock
    async def test_404_means_no_matches(self, http_client: httpx.AsyncClient) -> None:
        respx.get(DEFAULT_BASE_URL).respond(404, json={"error": {"code": "NOT_FOUND"}})
        with pytest.raises(UpstreamNotFoundError):
            await OpenFDAClient(http_client).search_labels("openfda.generic_name:none")

    @respx.mock
    async def test_429_is_retried_with_exponential_backoff_through_the_limiter(
        self, http_client: httpx.AsyncClient, fake_clock: FakeClock
    ) -> None:
        route = respx.get(DEFAULT_BASE_URL).mock(
            side_effect=[httpx.Response(429), httpx.Response(429), httpx.Response(200, json={"results": []})]
        )
        limiter = SlidingWindowRateLimiter(240, 60.0, clock=fake_clock, sleep=fake_clock.sleep)
        client = OpenFDAClient(
            http_client,
            rate_limiter=limiter,
            retry_policy=RetryPolicy(max_attempts=4, base_delay=0.5),
            sleep=fake_clock.sleep,
        )
        assert await client.search_labels("x") == []
        assert route.call_count == 3
        assert fake_clock.sleeps == [0.5, 1.0]
        assert len(limiter._dispatched) == 3  # every attempt consumed a rate-limit slot

    @respx.mock
    async def test_persistent_5xx_is_an_explicit_failure(
        self, http_client: httpx.AsyncClient, no_wait_policy: RetryPolicy
    ) -> None:
        route = respx.get(DEFAULT_BASE_URL).respond(500)
        with pytest.raises(UpstreamUnavailableError, match="after 3 attempts"):
            await OpenFDAClient(http_client, retry_policy=no_wait_policy).search_labels("x")
        assert route.call_count == 3

    @respx.mock
    @pytest.mark.parametrize("body", [{"meta": {}}, {"results": "nope"}])
    async def test_malformed_payload(self, http_client: httpx.AsyncClient, body: dict[str, Any]) -> None:
        respx.get(DEFAULT_BASE_URL).respond(200, json=body)
        with pytest.raises(UpstreamUnavailableError):
            await OpenFDAClient(http_client).search_labels("x")

    def test_retry_policy_delay_is_capped(self) -> None:
        policy = RetryPolicy(base_delay=1.0, max_delay=5.0)
        assert [policy.delay_for(i) for i in range(5)] == [1.0, 2.0, 4.0, 5.0, 5.0]
