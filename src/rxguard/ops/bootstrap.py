"""
One-shot production bootstrap (the compose ``bootstrap`` service; ``make refresh`` with --refresh).

1. ``alembic upgrade head``
2. seed the 500-drug catalogue (idempotent)
3. fetch and embed FDA labels, only when the corpus is empty (or --refresh): about 20 min for 500
4. build the generated rules, only when none exist (or --refresh)

Safe to re-run: steps that already happened are skipped, so every deploy can run it.
"""

import argparse
import asyncio
import logging
import os

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from src.rxguard.core.config import get_settings
from src.rxguard.database.connection import create_engine, create_session_factory
from src.rxguard.database.models import EvidencePassageRecord
from src.rxguard.ingestion import ingest_labels, seed_loader
from src.rxguard.safety import build_rules
from src.rxguard.safety.rules_db import GENERATED_RULES_DIR

logger = logging.getLogger(__name__)


def plan(passages: int, rules_exist: bool, refresh: bool) -> list[str]:
    """Which steps to run, given what the database and rules directory already hold."""
    steps = ["migrate", "seed"]
    if refresh or passages == 0:
        steps.append("ingest")
    if refresh or not rules_exist:
        steps.append("rules")
    return steps


async def _passage_count() -> int:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            return int(await session.scalar(select(func.count()).select_from(EvidencePassageRecord)) or 0)
    finally:
        await engine.dispose()


async def build_all_rules() -> None:
    """DDInter + label rules. DDInter is downloaded from an external server that has timed out before:
    if it fails, build the label rules alone so the deploy still comes up (``make refresh`` adds
    DDInter later). DDInter is CC BY-NC-SA, so it isn't downloaded at all when switched off."""
    if not get_settings().include_ddinter:
        await build_rules._main(["--skip-ddinter"])
        return
    try:
        await build_rules._main([])
    except httpx.HTTPError as exc:
        logger.warning("DDInter download failed (%s); building label rules only. Run a refresh later.", exc)
        await build_rules._main(["--skip-ddinter"])


async def run(refresh: bool, limit: int) -> None:
    """Steps after the migration (which ``main`` runs first: Alembic's async env needs its own loop)."""
    steps = plan(await _passage_count(), any(GENERATED_RULES_DIR.glob("*.json")), refresh)
    logger.info("bootstrap steps: %s", ", ".join(steps))
    await seed_loader._main([])
    if "ingest" in steps:
        await ingest_labels._main(["--limit", str(limit)])
    if "rules" in steps:
        await build_all_rules()
    logger.info("bootstrap complete")


def main() -> None:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(description="Migrate, seed, ingest labels and build rules.")
    parser.add_argument("--refresh", action="store_true", help="re-ingest labels and rebuild rules")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("LIMIT", "500")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    command.upgrade(Config("alembic.ini"), "head")  # before counting: the tables may not exist yet
    asyncio.run(run(args.refresh, args.limit))


if __name__ == "__main__":  # pragma: no cover
    main()
