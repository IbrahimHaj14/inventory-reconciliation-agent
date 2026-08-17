from datetime import UTC, datetime

import pytest

from reconciler.agent import run_agent
from reconciler.config import Settings
from reconciler.models import (
    REFUSAL_STATUSES,
    DecisionType,
    ReconciliationReport,
    SourceHealth,
    SourceName,
)
from reconciler.sources.simulated import load_scenario

_RUN_NOW = datetime(2026, 8, 17, tzinfo=UTC)


async def _run_scenario(name: str) -> ReconciliationReport:
    spec = load_scenario(f"scenarios/{name}.yaml")
    return await run_agent(spec, Settings(), _RUN_NOW)


def _health_by_source(report: ReconciliationReport) -> dict[SourceName, SourceHealth]:
    return {health.source: health for health in report.source_health}


def _assert_refusals_have_no_value(report: ReconciliationReport) -> None:
    assert all(
        sku.status not in REFUSAL_STATUSES or sku.reconciled_quantity is None
        for sku in report.skus
    )


@pytest.mark.asyncio
async def test_happy_path_reconciles_and_stops_early() -> None:
    spec = load_scenario("scenarios/happy_path.yaml")
    report = await run_agent(spec, Settings(), _RUN_NOW)

    assert all(sku.status is DecisionType.RECONCILE for sku in report.skus)
    assert len(report.sources_queried) < len(spec.sources)


@pytest.mark.asyncio
async def test_one_source_down_is_skipped_without_blocking_reconciliation() -> None:
    report = await _run_scenario("one_source_down")

    assert SourceName.WAREHOUSE_API in report.sources_skipped
    assert all(sku.status is DecisionType.RECONCILE for sku in report.skus)


@pytest.mark.asyncio
async def test_slow_source_has_reduced_latency_health_and_trust() -> None:
    report = await _run_scenario("slow_source")
    health_by_source = _health_by_source(report)
    slow_health = health_by_source[SourceName.WAREHOUSE_API]
    other_health = [
        health
        for source, health in health_by_source.items()
        if source is not SourceName.WAREHOUSE_API
    ]

    assert all(slow_health.latency_health < health.latency_health for health in other_health)
    assert all(slow_health.trust < health.trust for health in other_health)
    assert any(
        record.subject == SourceName.WAREHOUSE_API.value
        and "latency" in record.rationale.lower()
        for record in report.decision_log
    )


@pytest.mark.asyncio
async def test_stale_majority_never_supplies_a_reconciled_value() -> None:
    report = await _run_scenario("stale_majority")
    health_by_source = _health_by_source(report)

    assert health_by_source[SourceName.INTERNAL_DB].freshness == pytest.approx(0.0)
    assert health_by_source[SourceName.WAREHOUSE_API].freshness == pytest.approx(0.0)
    for sku in report.skus:
        assert sku.status in {
            DecisionType.RECONCILE,
            DecisionType.ESCALATE_INSUFFICIENT,
        }
        if sku.status is DecisionType.RECONCILE:
            assert sku.reconciled_quantity == 412
        else:
            assert sku.reconciled_quantity is None
        assert sku.reconciled_quantity != 999


@pytest.mark.asyncio
async def test_contradiction_explicitly_refuses_and_distrusts_outlier() -> None:
    report = await _run_scenario("contradiction")

    assert all(sku.status is DecisionType.FLAG_CONTRADICTION for sku in report.skus)
    assert all(sku.reconciled_quantity is None for sku in report.skus)
    assert all(SourceName.WAREHOUSE_API in sku.distrusted_sources for sku in report.skus)
    _assert_refusals_have_no_value(report)


@pytest.mark.asyncio
async def test_total_blackout_escalates_without_fabricating_values() -> None:
    report = await _run_scenario("total_blackout")

    assert all(sku.status is DecisionType.ESCALATE_INSUFFICIENT for sku in report.skus)
    assert all(sku.reconciled_quantity is None for sku in report.skus)
    _assert_refusals_have_no_value(report)
