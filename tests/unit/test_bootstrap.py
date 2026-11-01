"""Production bootstrap: only the steps that haven't happened yet run on a redeploy."""

from src.labelsafe.ops.bootstrap import plan


def test_first_boot_runs_everything() -> None:
    assert plan(passages=0, rules_exist=False, refresh=False) == ["migrate", "seed", "ingest", "rules"]


def test_redeploy_skips_ingest_and_rules_that_already_exist() -> None:
    assert plan(passages=4292, rules_exist=True, refresh=False) == ["migrate", "seed"]


def test_refresh_forces_ingest_and_rules() -> None:
    assert plan(passages=4292, rules_exist=True, refresh=True) == ["migrate", "seed", "ingest", "rules"]


async def test_a_ddinter_outage_still_builds_label_rules(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    from src.labelsafe.ops import bootstrap

    calls: list[list[str]] = []

    async def fake_build(argv: list[str]) -> None:
        calls.append(argv)
        if "--skip-ddinter" not in argv:
            raise httpx.ReadTimeout("ddinter.scbdd.com timed out")

    monkeypatch.setattr(bootstrap.build_rules, "_main", fake_build)
    await bootstrap.build_all_rules()
    assert calls == [[], ["--skip-ddinter"]]  # tried DDInter, then fell back to label rules
