from datetime import UTC, datetime
from pathlib import Path

import pytest

from reconciler.models import QueryOutcome, SourceName
from reconciler.sources.simulated import (
    ScenarioSpec,
    SimulatedSource,
    SourceSpec,
    build_sources,
    load_scenario,
)

EXPECTED_SCENARIOS = {
    "contradiction",
    "happy_path",
    "one_source_down",
    "slow_source",
    "stale_majority",
    "total_blackout",
}


def test_all_scenario_files_load() -> None:
    scenario_paths = sorted(Path("scenarios").glob("*.yaml"))

    assert {path.stem for path in scenario_paths} == EXPECTED_SCENARIOS
    for path in scenario_paths:
        assert isinstance(load_scenario(str(path)), ScenarioSpec)


@pytest.mark.asyncio
async def test_ok_source_returns_records_with_past_timestamp() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    source = SimulatedSource(
        name=SourceName.INTERNAL_DB,
        spec=SourceSpec(outcome=QueryOutcome.OK, age_s=10.0, records={"SKU-A": 412}),
        now=now,
    )

    result = await source.query(["SKU-A"])

    assert result.records == {"SKU-A": 412}
    assert result.data_timestamp is not None
    assert (now - result.data_timestamp).total_seconds() == 10.0


@pytest.mark.asyncio
async def test_unavailable_source_returns_no_data() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    source = SimulatedSource(
        name=SourceName.WAREHOUSE_API,
        spec=SourceSpec(outcome=QueryOutcome.UNAVAILABLE),
        now=now,
    )

    result = await source.query(["SKU-A"])

    assert result.records == {}
    assert result.data_timestamp is None
    assert result.error is not None


@pytest.mark.asyncio
async def test_fixed_seed_produces_identical_results() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    first_spec = load_scenario("scenarios/happy_path.yaml")
    second_spec = load_scenario("scenarios/happy_path.yaml")
    first_sources = build_sources(first_spec, now)
    second_sources = build_sources(second_spec, now)

    first_results = [await source.query(first_spec.skus) for source in first_sources]
    second_results = [await source.query(second_spec.skus) for source in second_sources]

    assert first_spec.seed == second_spec.seed
    assert first_results == second_results
