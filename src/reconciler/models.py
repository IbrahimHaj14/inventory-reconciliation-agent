from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class SourceName(StrEnum):
    WAREHOUSE_API = "warehouse_api"
    SUPPLIER_FEED = "supplier_feed"
    INTERNAL_DB = "internal_db"


class QueryOutcome(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    STALE = "stale"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class DecisionType(StrEnum):
    QUERY = "query"
    SKIP = "skip"
    RETRY = "retry"
    RECONCILE = "reconcile"
    FLAG_CONTRADICTION = "flag_contradiction"
    ESCALATE_INSUFFICIENT = "escalate_insufficient"
    FINALIZE = "finalize"


REFUSAL_STATUSES = {DecisionType.FLAG_CONTRADICTION, DecisionType.ESCALATE_INSUFFICIENT}


class SourceQueryResult(BaseModel):
    source: SourceName
    outcome: QueryOutcome
    latency_s: float
    records: dict[str, int] = Field(default_factory=dict)
    data_timestamp: datetime | None = None
    error: str | None = None


class SourceHealth(BaseModel):
    source: SourceName
    freshness: float
    latency_health: float
    reliability: float
    corroboration: float
    trust: float
    circuit_state: str
    reason: str


class DecisionRecord(BaseModel):
    step: int
    decision: DecisionType
    subject: str
    rationale: str
    evidence: dict[str, float] = Field(default_factory=dict)
    timestamp: datetime


class SkuReconciliation(BaseModel):
    sku: str
    status: DecisionType
    reconciled_quantity: int | None
    confidence: float
    support: float
    margin: float
    contributing_sources: list[SourceName] = Field(default_factory=list)
    distrusted_sources: list[SourceName] = Field(default_factory=list)
    note: str

    @model_validator(mode="after")
    def _refusal_has_no_value(self) -> SkuReconciliation:
        if self.status in REFUSAL_STATUSES and self.reconciled_quantity is not None:
            raise ValueError(
                f"INVARIANT VIOLATED: {self.status} must not carry a reconciled_quantity"
            )
        return self


class ReconciliationReport(BaseModel):
    generated_at: datetime
    scenario: str
    sources_queried: list[SourceName] = Field(default_factory=list)
    sources_skipped: list[SourceName] = Field(default_factory=list)
    source_health: list[SourceHealth] = Field(default_factory=list)
    decision_log: list[DecisionRecord] = Field(default_factory=list)
    skus: list[SkuReconciliation] = Field(default_factory=list)
    overall_note: str = ""
