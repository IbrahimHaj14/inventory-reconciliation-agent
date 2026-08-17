from datetime import UTC, datetime

import pytest

from reconciler.agent import run_agent
from reconciler.config import Settings
from reconciler.models import DecisionType
from reconciler.sources.simulated import load_scenario


@pytest.mark.asyncio
async def test_happy_path_reconciles_and_stops_early() -> None:
    spec = load_scenario("scenarios/happy_path.yaml")

    report = await run_agent(
        spec,
        Settings(),
        datetime(2026, 8, 17, tzinfo=UTC),
    )

    assert all(sku.status is DecisionType.RECONCILE for sku in report.skus)
    assert len(report.sources_queried) < len(spec.sources)
    assert len(report.decision_log) >= 3
