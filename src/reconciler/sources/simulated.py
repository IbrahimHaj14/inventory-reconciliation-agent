from datetime import datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from reconciler.config import settings
from reconciler.models import QueryOutcome, SourceName, SourceQueryResult


class SourceSpec(BaseModel):
    outcome: QueryOutcome = QueryOutcome.OK
    latency_s: float = 0.05
    age_s: float = 10.0
    records: dict[str, int] = Field(default_factory=dict)
    outcomes: list[QueryOutcome] | None = None


class ScenarioSpec(BaseModel):
    name: str
    seed: int = 0
    skus: list[str] = Field(default_factory=list)
    sources: dict[SourceName, SourceSpec]


class SimulatedSource:
    def __init__(self, name: SourceName, spec: SourceSpec, now: datetime) -> None:
        self.name = name
        self._spec = spec
        self._now = now
        self._call = 0

    async def query(self, skus: list[str]) -> SourceQueryResult:
        outcome = self._spec.outcome
        if self._spec.outcomes:
            outcome = self._spec.outcomes[min(self._call, len(self._spec.outcomes) - 1)]
        self._call += 1

        if outcome in {QueryOutcome.TIMEOUT, QueryOutcome.UNAVAILABLE, QueryOutcome.ERROR}:
            latency_s = self._spec.latency_s
            if outcome is QueryOutcome.TIMEOUT:
                latency_s = max(latency_s, settings.query_timeout_s)
            return SourceQueryResult(
                source=self.name,
                outcome=outcome,
                latency_s=latency_s,
                error=f"simulated {outcome.value}",
            )

        records = {sku: self._spec.records[sku] for sku in skus if sku in self._spec.records}
        if outcome is QueryOutcome.INVALID:
            future_offset_s = max(abs(self._spec.age_s), settings.freshness_half_life_s)
            data_timestamp = self._now + timedelta(seconds=future_offset_s)
        else:
            age_s = self._spec.age_s
            if outcome is QueryOutcome.STALE:
                age_s = max(
                    age_s,
                    settings.freshness_cutoff_s + settings.freshness_half_life_s,
                )
            data_timestamp = self._now - timedelta(seconds=age_s)

        return SourceQueryResult(
            source=self.name,
            outcome=outcome,
            latency_s=self._spec.latency_s,
            records=records,
            data_timestamp=data_timestamp,
        )


def load_scenario(path: str) -> ScenarioSpec:
    raw_scenario = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ScenarioSpec.model_validate(raw_scenario)


def build_sources(spec: ScenarioSpec, now: datetime) -> list[SimulatedSource]:
    return [
        SimulatedSource(name=name, spec=source_spec, now=now)
        for name, source_spec in spec.sources.items()
    ]
