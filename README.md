# Inventory Reconciliation Agent

## What it is

This project reconciles inventory quantities from a warehouse API, supplier feed, and internal
database when those sources may be slow, stale, unavailable, or contradictory. Its decision core
is deterministic: explicit rules and math produce an auditable report, and the optional LLM only
rephrases that completed report. The agent therefore refuses ambiguous or insufficient evidence
instead of confidently guessing a quantity.

## Quickstart

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are required.

```bash
uv sync
uv run reconcile run scenarios/contradiction.yaml
```

No API key is required. The deterministic template narrator is the default; setting
`ANTHROPIC_API_KEY` only enables an optional presentation-layer rephrasing.

## How it decides

For each SKU, confidence κ is `support × margin`. With the default settings, the decision rule is:

1. With no usable trusted candidates, return `ESCALATE_INSUFFICIENT` and no quantity.
2. When every provisional result has κ ≥ `kappa_high` (0.60) and margin ≥ `margin_min` (0.34),
   stop querying early.
3. At finalization, margin below 0.34 returns `FLAG_CONTRADICTION`; otherwise support below
   `support_min` (0.40) returns `ESCALATE_INSUFFICIENT`. Both statuses carry no quantity.
4. Otherwise return `RECONCILE` with the trust-weighted cluster value.

Trust is a gated weighted geometric mean of freshness, latency health, reliability, and
corroboration:

```text
T = clamp[0,1](gate × exp(Σ(weightᵢ × ln(max(factorᵢ, 10⁻⁹))) / Σweightᵢ))
```

An invalid, stale, failed, or circuit-blocked source receives a zero gate. Thresholds, weights,
timeouts, and half-lives are defined in `src/reconciler/config.py` and injected into the agent.

## Degradation scoring

- **Freshness:** exponential half-life decay, `2^(-age / half_life)`, with a hard stale cutoff.
- **Latency:** health relative to an exponentially weighted moving-average baseline.
- **Reliability:** Wilson lower confidence bound, so small success samples remain uncertain.
- **Corroboration:** exponential decay as a reading moves away from provisional consensus.

## Scenarios

| Scenario | Injected condition | Expected behavior |
|---|---|---|
| `happy_path` | Three fresh, agreeing sources | Reconcile and stop before querying every source |
| `one_source_down` | One unavailable source | Skip the failed source and reconcile from agreement |
| `slow_source` | One high-latency response | Reduce its latency health and trust before deciding |
| `stale_majority` | Two stale sources | Ignore stale values; use fresh evidence or escalate |
| `contradiction` | Fresh, high-trust values disagree | Flag contradiction and return no quantity |
| `total_blackout` | Sources are unavailable or stale | Escalate insufficient evidence and fabricate nothing |

## Architecture

The agent runs an explicit state machine:

1. **Plan:** compute source priority from expected freshness, observed reliability, and breaker
   state.
2. **Select and query:** choose the current highest-priority eligible source and query it
   asynchronously under a timeout.
3. **Assess and update:** validate timestamps, compute health/trust, update circuit breakers, and
   append the numeric decision trace.
4. **Decide next:** finalize early when confidence is decisive, query a tie-breaker on conflict,
   or continue while useful evidence remains.
5. **Finalize:** calculate provisional consensus, add corroboration, recompute final trust, apply
   the decision rule, and construct the validated report.

The optional LLM plugs in only after step 5. It receives serialized report data with instructions
not to alter any number, source, or decision; import, API, empty-output, or model failures fall back
to the deterministic template. No LLM dependency is imported by scoring, state, or agent modules.

## Tests

Run the complete quality gate:

```bash
uv run ruff check src tests
uv run mypy --strict src
uv run pytest --cov=src/reconciler --cov-report=term-missing -q
```

The current suite has 33 tests and 81% total statement coverage. `agent.py` is at 92%; every
scoring module is at least 86%, with consensus, freshness, latency, and reliability at 100%.
Hypothesis property tests cover trust bounds, reliability monotonicity, freshness monotonicity,
and the invariant that a refusal never carries a reconciled value. Scenario tests cover all six
degradation modes.

## What I'd do next

The external APIs are currently deterministic simulations, and reliability history is held only
in memory. Next steps would be SQLite-backed reliability history, bounded-concurrency async fan-out
across SKUs, online Bayesian reliability updates, drift detection for inter-source agreement, real
connectors behind the `Source` protocol, OpenTelemetry traces, a human-in-the-loop escalation queue,
and learned thresholds validated against operational data.
