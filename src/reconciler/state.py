from dataclasses import dataclass, field

from reconciler.models import DecisionRecord, SourceHealth, SourceName, SourceQueryResult


@dataclass
class SourceRuntime:
    successes: int = 0
    failures: int = 0
    last_result: SourceQueryResult | None = None
    health: SourceHealth | None = None


@dataclass
class AgentState:
    step: int = 0
    runtime: dict[SourceName, SourceRuntime] = field(default_factory=dict)
    queried: list[SourceName] = field(default_factory=list)
    skipped: list[SourceName] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    candidates: dict[str, list[tuple[int, float, SourceName]]] = field(default_factory=dict)

    def log(self, record: DecisionRecord) -> None:
        self.step += 1
        record.step = self.step
        self.decisions.append(record)
