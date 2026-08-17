# EXECUTION_PLAN.md — Build the Inventory Reconciliation Agent

> **Instructions to the coding agent (Codex):**
> Build this project **phase by phase, in order**. Do not skip ahead. After each phase:
> 1. Run the phase's **Verification Command**.
> 2. Run the full Definition-of-Done gate from `AGENTS.md`:
>    `uv run ruff check src tests && uv run mypy --strict src && uv run pytest -q`.
> 3. Only if both pass, proceed to the next phase. If anything fails, fix it first — do not
>    loosen types, delete tests, or add unlisted dependencies to make a gate pass.
>
> **Global rules (from `AGENTS.md`, repeated because they matter):**
> - `scoring/` functions are **pure**: no I/O, no `datetime.now()`, no globals, no randomness.
>   Age/time is always a float argument passed in.
> - The **LLM never makes a decision.** No `anthropic`/`instructor` import under `scoring/`,
>   `agent.py`, `state.py`, or `consensus.py`.
> - All thresholds/weights/timeouts come from `config.py`. No magic numbers in logic.
> - All normalized scores clamp to `[0, 1]`.
> - The system must run with **no API key set**.
> - The **refusal invariant** is sacred: a refused SKU has `reconciled_quantity = None`.

---

## Phase 1 — Repo Setup, `pyproject.toml`, Dependencies, `AGENTS.md`

**Phase Objective:** Establish a clean `uv`-managed Python 3.12 package that installs, imports,
type-checks, and lints on an empty skeleton.

**Files to Touch:**
`pyproject.toml`, `.gitignore`, `.env.example`, `AGENTS.md`, `README.md` (placeholder),
`src/reconciler/__init__.py`

**Exact Implementation Instructions:**

Place the provided `AGENTS.md` at the repo root unchanged.

Create `pyproject.toml` (src layout, hatchling backend, console script `reconcile`):

```toml
[project]
name = "inventory-reconciliation-agent"
version = "0.1.0"
description = "Deterministic multi-source inventory reconciliation agent"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "typer>=0.12",
    "rich>=13.7",
    "structlog>=24.1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
llm = ["anthropic>=0.39"]

[project.scripts]
reconcile = "reconciler.cli:app"

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "hypothesis>=6.100",
    "mypy>=1.10",
    "ruff>=0.5",
    "types-PyYAML>=6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/reconciler"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ANN", "SIM", "RUF"]
ignore = ["ANN401"]

[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "src"
packages = ["reconciler"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`.env.example`:
```
# Optional. The system runs fully without this. Only enables the LLM narrator.
ANTHROPIC_API_KEY=
```

`.gitignore`: standard Python + `.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`,
`.ruff_cache/`, `*.egg-info/`, `.env`, `report.json`.

`src/reconciler/__init__.py`: `__version__ = "0.1.0"`.

**Verification Command:**
```
uv sync && uv run python -c "import reconciler; print(reconciler.__version__)" && \
uv run ruff check src && uv run mypy --strict src
```

**Success Criteria:** `uv.lock` is created, the import prints `0.1.0`, ruff and mypy report no
errors on the empty package.

---

## Phase 2 — Data Models (`models.py`) and Config (`config.py`)

**Phase Objective:** Define the entire typed contract of the system and enforce the refusal
invariant at the schema level.

**Files to Touch:**
`src/reconciler/models.py`, `src/reconciler/config.py`, `tests/test_models.py`

**Exact Implementation Instructions:**

`models.py` — enums and models (Pydantic v2). Implement exactly these:

```python
from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, model_validator

class SourceName(str, Enum):
    WAREHOUSE_API = "warehouse_api"
    SUPPLIER_FEED = "supplier_feed"
    INTERNAL_DB   = "internal_db"

class QueryOutcome(str, Enum):
    OK = "ok"; TIMEOUT = "timeout"; ERROR = "error"; STALE = "stale"
    INVALID = "invalid"; UNAVAILABLE = "unavailable"

class DecisionType(str, Enum):
    QUERY = "query"; SKIP = "skip"; RETRY = "retry"
    RECONCILE = "reconcile"
    FLAG_CONTRADICTION = "flag_contradiction"
    ESCALATE_INSUFFICIENT = "escalate_insufficient"
    FINALIZE = "finalize"

REFUSAL_STATUSES = {DecisionType.FLAG_CONTRADICTION, DecisionType.ESCALATE_INSUFFICIENT}

class SourceQueryResult(BaseModel):
    source: SourceName
    outcome: QueryOutcome
    latency_s: float
    records: dict[str, int] = Field(default_factory=dict)   # sku -> quantity
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
    subject: str                       # source name or SKU
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
    def _refusal_has_no_value(self) -> "SkuReconciliation":
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
```

`config.py` — pydantic-settings with defaults. All logic reads from here:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REC_", env_file=".env")

    # decision thresholds
    kappa_high: float = 0.6
    margin_min: float = 0.34
    support_min: float = 0.4
    cluster_tolerance: int = 2          # units; values within this are "the same reading"

    # trust weights (freshness, latency, reliability, corroboration)
    w_freshness: float = 1.0
    w_latency: float = 0.6
    w_reliability: float = 1.0
    w_corroboration: float = 1.2

    # freshness
    freshness_half_life_s: float = 120.0
    freshness_cutoff_s: float = 1800.0

    # latency
    latency_ewma_alpha: float = 0.3

    # reliability
    wilson_z: float = 1.28

    # corroboration scale (tolerance unit for exp decay)
    corroboration_scale: float = 5.0

    # circuit breaker
    breaker_failure_threshold: int = 3
    breaker_cooldown_s: float = 30.0

    # per-source query timeout
    query_timeout_s: float = 2.0

    # retry budget per run
    max_retries_per_source: int = 1

settings = Settings()
```

`tests/test_models.py`: assert that constructing a `SkuReconciliation` with
`status=FLAG_CONTRADICTION` and `reconciled_quantity=5` raises `ValidationError`, and that the
same status with `reconciled_quantity=None` succeeds. Assert a `RECONCILE` with a value succeeds.

**Verification Command:**
```
uv run mypy --strict src/reconciler/models.py src/reconciler/config.py && \
uv run pytest tests/test_models.py -q
```

**Success Criteria:** mypy clean; the refusal-invariant test passes (value on a refusal status
raises, `None` on a refusal status passes).

---

## Phase 3 — Pure Math Scoring Engine (`scoring/*`) + Unit Tests

**Phase Objective:** Implement every degradation-quantifying function as a pure, unit-tested
function with known-value assertions.

**Files to Touch:**
`src/reconciler/scoring/{__init__,freshness,latency,reliability,consensus,trust}.py`,
`tests/test_freshness.py`, `tests/test_latency.py`, `tests/test_reliability.py`,
`tests/test_consensus.py`, `tests/test_trust.py`

**Exact Implementation Instructions:**

`scoring/freshness.py`:
```python
def freshness(age_s: float, half_life_s: float, cutoff_s: float | None = None) -> float:
    if age_s < 0:                       # future timestamp = integrity failure
        return 0.0
    if cutoff_s is not None and age_s > cutoff_s:
        return 0.0
    return 2 ** (-age_s / half_life_s)
```

`scoring/latency.py`:
```python
class LatencyTracker:
    def __init__(self, alpha: float = 0.3) -> None:
        self.alpha = alpha
        self.ewma: float | None = None

    def observe(self, latency_s: float) -> None:
        self.ewma = (
            latency_s if self.ewma is None
            else self.alpha * latency_s + (1 - self.alpha) * self.ewma
        )

    def health(self, latency_s: float) -> float:
        if not self.ewma:
            return 1.0
        return min(1.0, self.ewma / max(latency_s, 1e-9))
```

`scoring/reliability.py`:
```python
import math

def wilson_lower_bound(successes: int, failures: int, z: float = 1.28) -> float:
    n = successes + failures
    if n == 0:
        return 0.5                      # neutral prior for an unseen source
    p = successes / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    return max(0.0, min(1.0, (centre - margin) / denom))
```

`scoring/consensus.py` — corroboration + the clustering decision rule. `reconcile` returns a
lightweight dataclass (keep `scoring/` free of Pydantic-heavy coupling):
```python
import math
from dataclasses import dataclass

def corroboration(value: float, consensus: float, scale: float) -> float:
    return math.exp(-abs(value - consensus) / max(scale, 1e-9))

@dataclass(frozen=True)
class Reconciliation:
    value: int | None
    status: str            # "RECONCILE" | "FLAG_CONTRADICTION" | "ESCALATE_INSUFFICIENT"
    support: float
    margin: float
    confidence: float

def reconcile(
    candidates: list[tuple[int, float]],   # (reported_value, trust)
    total_expected_trust: float,           # = number of configured sources (max trust each = 1)
    tol: int,
    k_high: float,
    m_min: float,
    support_min: float,
) -> Reconciliation:
    usable = [(v, t) for v, t in candidates if t > 0.0]
    if not usable or total_expected_trust <= 0:
        return Reconciliation(None, "ESCALATE_INSUFFICIENT", 0.0, 0.0, 0.0)

    clusters: list[list[float]] = []       # each: [weighted_value_sum, trust_sum]
    for value, trust in sorted(usable):
        placed = False
        for c in clusters:
            if abs(value - c[0] / c[1]) <= tol:
                c[0] += value * trust
                c[1] += trust
                placed = True
                break
        if not placed:
            clusters.append([value * trust, trust])

    clusters.sort(key=lambda c: c[1], reverse=True)
    w_top = clusters[0][1]
    w_2nd = clusters[1][1] if len(clusters) > 1 else 0.0

    support = min(1.0, w_top / total_expected_trust)
    margin = (w_top - w_2nd) / (w_top + w_2nd) if (w_top + w_2nd) else 1.0
    confidence = support * margin
    value = round(clusters[0][0] / w_top)

    if margin < m_min:
        return Reconciliation(None, "FLAG_CONTRADICTION", support, margin, confidence)
    if support < support_min:
        return Reconciliation(None, "ESCALATE_INSUFFICIENT", support, margin, confidence)
    return Reconciliation(value, "RECONCILE", support, margin, confidence)
```

`scoring/trust.py` — gated weighted geometric mean, generic over factors:
```python
import math

def geometric_trust(factors: list[tuple[float, float]], gate: float) -> float:
    """factors: list of (value in [0,1], weight). gate in {0.0, 1.0}."""
    den = sum(w for _, w in factors)
    if den <= 0:
        return 0.0
    num = sum(w * math.log(max(v, 1e-9)) for v, w in factors)
    return max(0.0, min(1.0, gate * math.exp(num / den)))
```

**Tests (known values):**
- `freshness`: `freshness(0, 120) == 1.0`; `freshness(120, 120) == 0.5`;
  `freshness(2000, 120, cutoff_s=1800) == 0.0`; `freshness(-1, 120) == 0.0`.
- `LatencyTracker`: after `observe(0.3)` twice, `health(0.3) == 1.0` and `health(0.6) == 0.5`.
- `wilson_lower_bound`: `wilson_lower_bound(0, 0) == 0.5`; result of `(2, 0)` is `< 1.0` and
  `> (10, 0)`'s is `>` `(2, 0)`'s (more evidence ⇒ higher lower bound).
- `reconcile`: two agreeing high-trust values ⇒ `RECONCILE` with that value; two far-apart
  high-trust values ⇒ `FLAG_CONTRADICTION` and `value is None`; all-zero-trust ⇒
  `ESCALATE_INSUFFICIENT` and `value is None`.
- `geometric_trust`: `geometric_trust([(0.9,1),(0.9,1)], 1.0)` ≈ 0.9; any factor at ~0 collapses
  the result toward 0; `gate=0.0` ⇒ `0.0`.

**Verification Command:**
```
uv run mypy --strict src/reconciler/scoring && \
uv run pytest tests/test_freshness.py tests/test_latency.py tests/test_reliability.py \
              tests/test_consensus.py tests/test_trust.py -q
```

**Success Criteria:** all scoring tests green; mypy strict clean on `scoring/`.

---

## Phase 4 — Chaos Simulator & Scenario YAML (`sources/*`, `scenarios/*`)

**Phase Objective:** Provide a deterministic, seeded source layer that reproduces every failure
mode on demand, driven by declarative scenario files.

**Files to Touch:**
`src/reconciler/sources/{__init__,base.py,simulated.py}`, `scenarios/*.yaml`,
`tests/test_sources.py`

**Exact Implementation Instructions:**

`sources/base.py` — the async protocol every source (real or fake) implements:
```python
from typing import Protocol
from reconciler.models import SourceName, SourceQueryResult

class Source(Protocol):
    name: SourceName
    async def query(self, skus: list[str]) -> SourceQueryResult: ...
```

`sources/simulated.py` — scenario spec + deterministic injector. Compute `data_timestamp`
from `age_s` relative to a **run clock passed in** (do not read the wall clock inside scoring,
but the simulator may accept a `now` reference). Model:
```python
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from reconciler.models import SourceName, QueryOutcome, SourceQueryResult

class SourceSpec(BaseModel):
    outcome: QueryOutcome = QueryOutcome.OK
    latency_s: float = 0.05
    age_s: float = 10.0
    records: dict[str, int] = Field(default_factory=dict)
    outcomes: list[QueryOutcome] | None = None   # optional per-call sequence (flapping/silent)

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
        # UNAVAILABLE/TIMEOUT ⇒ no records, no timestamp. STALE ⇒ force old timestamp.
        # OK ⇒ records + timestamp = now - age_s. INVALID ⇒ future timestamp.
        ...
```
Also provide `load_scenario(path: str) -> ScenarioSpec` (parse YAML with `pyyaml`) and a
`build_sources(spec, now) -> list[SimulatedSource]`.

Behavior mapping the simulator must implement:
- `OK` → returns `records`, `data_timestamp = now - age_s`, given `latency_s`.
- `STALE` → returns `records` but `data_timestamp` far past `freshness_cutoff_s`.
- `TIMEOUT` / `UNAVAILABLE` → `records={}`, `data_timestamp=None`, `error` set. Latency for
  `TIMEOUT` should equal/exceed `query_timeout_s`.
- `ERROR` → `records={}`, `error` set.
- `INVALID` → `data_timestamp` set to a **future** time (so freshness validation rejects it).

Write these 6 scenario files (extend with `flapping.yaml`/`goes_silent.yaml` if time allows):

`scenarios/happy_path.yaml` — all `ok`, fresh, agreeing (e.g. SKU-A: 412 / 412 / 411).
`scenarios/one_source_down.yaml` — one `unavailable`, others fresh & agree.
`scenarios/slow_source.yaml` — one `ok` but `latency_s` ≫ others; others fresh.
`scenarios/stale_majority.yaml` — two `stale`, one `ok` fresh.
`scenarios/contradiction.yaml` — two fresh high-trust sources with far-apart values (412 vs 999),
one `ok` closer to 412.
`scenarios/total_blackout.yaml` — all `unavailable`/`stale`.

Example (`scenarios/contradiction.yaml`):
```yaml
name: contradiction
seed: 42
skus: [SKU-A]
sources:
  internal_db:   { outcome: ok, latency_s: 0.05, age_s: 12, records: { SKU-A: 412 } }
  warehouse_api: { outcome: ok, latency_s: 0.06, age_s: 30, records: { SKU-A: 999 } }
  supplier_feed: { outcome: ok, latency_s: 0.08, age_s: 45, records: { SKU-A: 410 } }
```

`tests/test_sources.py`: assert each scenario file loads into a `ScenarioSpec`; assert a
`SimulatedSource` with `outcome=ok` returns the configured records and a timestamp `age_s` in the
past; assert `outcome=unavailable` returns empty records and `data_timestamp is None`; assert a
fixed seed produces identical results across two runs.

**Verification Command:**
```
uv run mypy --strict src/reconciler/sources && \
uv run pytest tests/test_sources.py -q && \
uv run python -c "from reconciler.sources.simulated import load_scenario; \
import glob; [load_scenario(p) for p in glob.glob('scenarios/*.yaml')]; print('scenarios ok')"
```

**Success Criteria:** all 6 scenarios parse; simulator reproduces injected conditions
deterministically; source tests green.

---

## Phase 5 — Circuit Breakers, Agent State & Core Decision Loop

**Phase Objective:** Implement the resilience primitive, the accumulating state, and the
dynamic (non-fixed) decision loop that produces a `ReconciliationReport`.

**Files to Touch:**
`src/reconciler/circuit_breaker.py`, `src/reconciler/state.py`, `src/reconciler/agent.py`,
`tests/test_circuit_breaker.py`, `tests/test_agent_smoke.py`

**Exact Implementation Instructions:**

`circuit_breaker.py` — 3-state breaker; `now` passed in (pure of wall clock):
```python
from enum import Enum

class BreakerState(str, Enum):
    CLOSED = "closed"; OPEN = "open"; HALF_OPEN = "half_open"

class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_s: float) -> None: ...
    @property
    def state(self) -> BreakerState: ...
    def allow(self, now: float) -> bool:          # False ⇒ skip source (gate = 0)
        ...
    def record_success(self, now: float) -> None: ...
    def record_failure(self, now: float) -> None: ...
```
Transitions: `CLOSED --(≥ failure_threshold consecutive failures)--> OPEN`;
`OPEN --(now - opened_at ≥ cooldown_s, on allow())--> HALF_OPEN`;
`HALF_OPEN --success--> CLOSED`, `HALF_OPEN --failure--> OPEN`.

`state.py` — accumulating, inspectable run state:
```python
from dataclasses import dataclass, field
from reconciler.models import SourceName, DecisionRecord, SourceQueryResult, SourceHealth

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
    # per-sku accumulated candidates: sku -> list[(value, trust, source)]
    candidates: dict[str, list[tuple[int, float, SourceName]]] = field(default_factory=dict)

    def log(self, record: DecisionRecord) -> None: ...
```

`agent.py` — the state machine. Structure the loop as explicit phases; **query order is computed
from state, not hardcoded**, and the loop **early-stops** when confidence is decisive:

```
PLAN
  → compute initial source priority = f(prior reliability, expected freshness, breaker state)
LOOP over selected sources (dynamic):
  SELECT_SOURCE  – pick highest-priority not-yet-queried source whose breaker allows()
  QUERY          – await source.query(skus) under asyncio.wait_for(timeout)
                   timeout/exception ⇒ record failure on breaker, outcome TIMEOUT/UNAVAILABLE
  ASSESS         – validate timestamp (reject future/malformed ⇒ INVALID)
                   compute F (freshness), L (latency health), R (wilson) → intrinsic trust
                   (gated geometric of F,L,R). Build SourceHealth with a human `reason`.
  UPDATE         – push (value, intrinsic_trust, source) per sku into state.candidates;
                   update breaker + successes/failures; append DecisionRecord (QUERY/SKIP/RETRY)
  DECIDE_NEXT    – run a PROVISIONAL reconcile per sku with intrinsic trust:
                   • if all skus already decisive (κ ≥ kappa_high and margin ≥ margin_min):
                       FINALIZE early (do NOT query remaining sources) – log the early-stop
                   • if a contradiction is detected and an unqueried source remains:
                       CONTINUE (query a tie-breaker) – log why
                   • else CONTINUE / SKIP degraded sources
FINALIZE (two-pass corroboration to avoid circular reasoning):
  1. provisional consensus per sku from intrinsic-trust-weighted reconcile
  2. C_i = corroboration(value_i, consensus, corroboration_scale)
  3. final trust T_i = gated geometric of (F, L, R, C)
  4. final reconcile(candidates_with_T, total_expected_trust = #configured_sources, …)
  5. map Reconciliation → SkuReconciliation (status str → DecisionType);
     record contributing vs distrusted sources; enforce refusal invariant via the model
REPORT – assemble ReconciliationReport (health, full decision_log, skus)
```

Every branch appends a `DecisionRecord` whose `evidence` dict holds the **actual numbers**
(e.g. `{"latency_s": 4.1, "baseline_s": 0.3, "age_s": 22320, "trust": 0.18}`) and whose
`rationale` is a plain-English sentence. Requirement: at least **three** sequential
`DecisionType.QUERY`/`SKIP`/`RETRY`/`FINALIZE` records driven by observed state per run.

Expose: `async def run_agent(spec: ScenarioSpec, settings: Settings, now: datetime) -> ReconciliationReport`.

**Tests:**
- `test_circuit_breaker.py`: threshold failures → `OPEN`; `allow()` false while open before
  cooldown; after cooldown → `HALF_OPEN`; success → `CLOSED`; failure in half-open → `OPEN`.
- `test_agent_smoke.py`: run `happy_path.yaml` → all SKUs `RECONCILE`; assert the agent
  **queried fewer than all sources** (early stop) and that `len(report.decision_log) >= 3`.

**Verification Command:**
```
uv run mypy --strict src/reconciler && \
uv run pytest tests/test_circuit_breaker.py tests/test_agent_smoke.py -q
```

**Success Criteria:** breaker transitions correct; happy path reconciles and early-stops with a
decision log of ≥3 records; mypy strict clean across `src/`.

---

## Phase 6 — Report Serializer, Narrator, and Rich CLI

**Phase Objective:** Turn the report into both machine-auditable JSON and operator-readable
prose, and expose a one-command CLI that runs with no API key.

**Files to Touch:**
`src/reconciler/narrator.py`, `src/reconciler/cli.py`, `tests/test_narrator.py`

**Exact Implementation Instructions:**

`narrator.py`:
```python
from reconciler.models import ReconciliationReport

def render_template(report: ReconciliationReport) -> str:
    """Deterministic, no-LLM narrative built ONLY from report fields.
    States, per source: whether used/skipped/distrusted and why (with numbers).
    Per SKU: reconciled value + confidence, OR the explicit refusal + reason."""
    ...

def render_narrative(report: ReconciliationReport) -> str:
    """Default = render_template. If ANTHROPIC_API_KEY is set AND anthropic import succeeds,
    pass the report JSON to the model with a strict instruction: rephrase for readability,
    DO NOT introduce or alter any number, source, or decision. On ANY failure, fall back to
    render_template. The LLM must never be on the decision path — this is presentation only."""
    ...
```

`cli.py` (typer + rich):
```python
import typer
from rich.console import Console
# command: reconcile run <scenario.yaml> [--json report.json]
# - load scenario, run_agent, then:
#   * stream the decision_log as a rich table/log (step, decision, subject, rationale)
#   * print a per-source health table (trust, freshness, latency_health, reliability, reason)
#   * print a per-SKU results table (value or "REFUSED", status, confidence)
#   * print render_narrative(report)
#   * write report.model_dump_json(indent=2) to --json path (default report.json)
app = typer.Typer()
```

`tests/test_narrator.py`: build a `ReconciliationReport` with a `FLAG_CONTRADICTION` SKU; assert
`render_template` output contains the SKU, the word for refusal, and does **not** print a
reconciled quantity for it. Assert `render_narrative` returns the template output when no API
key is set (monkeypatch env to unset).

**Verification Command:**
```
uv run mypy --strict src/reconciler/narrator.py src/reconciler/cli.py && \
uv run pytest tests/test_narrator.py -q && \
env -u ANTHROPIC_API_KEY uv run reconcile run scenarios/contradiction.yaml --json /tmp/r.json && \
uv run python -c "import json; d=json.load(open('/tmp/r.json')); \
assert any(s['status']=='flag_contradiction' and s['reconciled_quantity'] is None for s in d['skus']); \
print('refusal ok')"
```

**Success Criteria:** CLI runs with the API key unset; `report.json` is written; the
contradiction scenario yields a SKU with `status=flag_contradiction` and `reconciled_quantity=null`.

---

## Phase 7 — Property-Based Invariant Tests & Scenario Suite

**Phase Objective:** Prove the mathematical invariants hold for arbitrary inputs and that each
chaos scenario produces the correct decision outcome.

**Files to Touch:**
`tests/test_invariants.py`, `tests/test_scenarios.py`

**Exact Implementation Instructions:**

`tests/test_invariants.py` (hypothesis):
- **Trust ∈ [0,1]:** for arbitrary factor values in `[0,1]` and positive weights,
  `geometric_trust(...)` ∈ `[0,1]`; with `gate=0.0` it is exactly `0.0`.
- **Reliability monotonicity:** for arbitrary `n` and `k ≤ n`, adding one more success never
  decreases `wilson_lower_bound`, and the result ∈ `[0,1]`.
- **Freshness bounds & monotonicity:** `freshness ∈ [0,1]`; non-increasing in `age_s`.
- **Refusal invariant (the important one):** for arbitrary `candidates` and thresholds,
  whenever `reconcile(...).status` is `"FLAG_CONTRADICTION"` or `"ESCALATE_INSUFFICIENT"`,
  `reconcile(...).value is None`. And whenever it is `"RECONCILE"`, `value is not None`.

`tests/test_scenarios.py` (run each scenario through `run_agent`, assert the outcome):
| Scenario | Assert |
|---|---|
| `happy_path` | all SKUs `RECONCILE`; agent early-stopped (queried < all sources) |
| `one_source_down` | down source in `sources_skipped`; SKUs still `RECONCILE` from the rest |
| `slow_source` | slow source has lowest `latency_health`; its trust reduced; decision log notes it |
| `stale_majority` | stale sources have `freshness≈0`; either reconcile to fresh or escalate — never to a stale value |
| `contradiction` | SKU status `FLAG_CONTRADICTION`, `reconciled_quantity is None`; warehouse in `distrusted_sources` |
| `total_blackout` | every SKU `ESCALATE_INSUFFICIENT`, all `reconciled_quantity is None`; no fabricated value anywhere |

Add an assertion in the contradiction/blackout tests that **no** `SkuReconciliation` in the
report has both a refusal status and a non-null quantity (belt-and-braces on invariant #1).

**Verification Command:**
```
uv run pytest tests/test_invariants.py tests/test_scenarios.py -q && \
uv run pytest --cov=src/reconciler --cov-report=term-missing -q
```

**Success Criteria:** all property tests pass (hypothesis finds no counterexample); every
scenario asserts its expected outcome; coverage on `scoring/` and `agent.py` ≥ 85%.

---

## Phase 8 — Verification, Formatting, and README Generation

**Phase Objective:** Ship a clean, documented, reproducible repo that a reviewer can run in one
command with zero setup.

**Files to Touch:**
`README.md`, `examples/sample_report.json`, final format pass across `src/` and `tests/`

**Exact Implementation Instructions:**

Generate `examples/sample_report.json` by running the contradiction scenario and committing its
output (this lets a reviewer see a real report without running anything).

Write `README.md` with these sections (prose, concise, honest):
1. **What it is** — one paragraph + the design thesis: deterministic decision core, LLM only
   narrates, so it never confidently guesses.
2. **Quickstart** — `uv sync` then `uv run reconcile run scenarios/contradiction.yaml`
   (state clearly: no API key required).
3. **How it decides** — the 4-line decision rule (κ_high / margin_min / support_min) and the
   gated-geometric trust formula, in plain words.
4. **Degradation scoring** — one line each for freshness (half-life), latency (EWMA),
   reliability (Wilson LB), corroboration.
5. **Scenarios** — the table from Phase 7 (what each injects, what the agent does).
6. **Architecture** — the state-machine phase list; where the optional LLM plugs in and its
   guardrails.
7. **Tests** — how to run; coverage %; note the property-based invariants.
8. **What I'd do next** — persist reliability history (SQLite); bounded-concurrency async
   fan-out across SKUs; online Bayesian reliability update; drift detection on inter-source
   agreement; real connectors behind the `Source` protocol; OpenTelemetry traces; human-in-loop
   escalation queue; learned thresholds. Be honest about what is stubbed (real APIs are
   simulated; reliability history is in-memory).

Run the full gate and a couple of end-to-end scenarios as the final proof.

**Verification Command:**
```
uv run ruff format src tests && \
uv run ruff check src tests && \
uv run mypy --strict src && \
uv run pytest --cov=src/reconciler --cov-report=term-missing -q && \
env -u ANTHROPIC_API_KEY uv run reconcile run scenarios/total_blackout.yaml --json /tmp/blackout.json && \
uv run python -c "import json; d=json.load(open('/tmp/blackout.json')); \
assert all(s['reconciled_quantity'] is None for s in d['skus']); print('blackout refuses to guess: ok')"
```

**Success Criteria:** ruff (lint + format), mypy strict, and the full pytest suite are all green;
coverage target met; `README.md` and `examples/sample_report.json` exist; the blackout scenario
returns no fabricated quantities; the whole thing ran with `ANTHROPIC_API_KEY` unset.

---

## Final acceptance (run once, all must pass)

```
uv sync
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest --cov=src/reconciler --cov-report=term-missing -q
env -u ANTHROPIC_API_KEY uv run reconcile run scenarios/happy_path.yaml
env -u ANTHROPIC_API_KEY uv run reconcile run scenarios/contradiction.yaml
env -u ANTHROPIC_API_KEY uv run reconcile run scenarios/total_blackout.yaml
```

If every command above passes and the three scenarios print (a) an early-stopped reconcile,
(b) an explicit contradiction refusal, and (c) an insufficient-data escalation with **no
fabricated quantities**, the build matches the blueprint. Then: confirm the GitHub repo is
**public** by opening it in a logged-out browser window before submitting.
