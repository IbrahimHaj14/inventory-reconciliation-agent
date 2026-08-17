# AGENTS.md — Multi-Source Inventory Reconciliation Agent

> Read this file before doing anything. Every rule here is a hard constraint, not a suggestion.

## What this project is

A **deterministic** multi-source inventory reconciliation agent. It reconciles inventory
quantities across several external sources (warehouse API, supplier feed, internal DB) that
may be unavailable, slow, stale, or contradictory. Trust and every decision are computed by
**explicit math and rules — never by an LLM.** The LLM (optional) only turns a ground-truth
decision trace into operator-readable prose. The core value of this system is that it
**refuses to guess** when data is insufficient, and can explain exactly why.

## Environment & commands

- Python **3.12+**. Dependency + venv manager: **`uv`**.

| Purpose | Command |
|---|---|
| Install / sync deps | `uv sync` |
| Run a scenario | `uv run reconcile run scenarios/<name>.yaml` |
| Run all tests | `uv run pytest -q` |
| Coverage | `uv run pytest --cov=src/reconciler --cov-report=term-missing` |
| Type check (strict) | `uv run mypy --strict src` |
| Lint | `uv run ruff check src tests` |
| Format | `uv run ruff format src tests` |

The system **MUST run end-to-end with no `ANTHROPIC_API_KEY` set.** The LLM narrator is
optional; a deterministic template narrator is the default and the fallback.

## Definition of done (applies to every change)

A change is complete only when **all three** pass, in this order:

1. `uv run ruff check src tests` → 0 errors
2. `uv run mypy --strict src` → 0 errors
3. `uv run pytest -q` → all green

Never mark a phase complete until its Verification Command passes. If a gate fails, fix it
before moving on. Do not disable rules or loosen types to make a gate pass.

## Coding standards

- **Full type hints** on every function, parameter, and return value. `mypy --strict` clean.
- **No bare `Any`.** No untyped `dict` crossing a module boundary — use a Pydantic model.
- **`scoring/` is pure.** No I/O, no clock reads, no globals, no randomness. Time and age are
  always passed **in** as floats; a scoring function never calls `datetime.now()`.
- **All source I/O is `async`** and every external query has a **timeout**.
- **No magic numbers in logic.** All thresholds, weights, timeouts, half-lives live in
  `config.py` (pydantic-settings) and are injected.
- **All normalized scores are clamped to `[0, 1]`.**
- **Determinism.** Simulated sources take a `seed`. Same seed + same scenario ⇒ identical run.
- Keep dependencies to the list in `pyproject.toml`. Do not add new ones without cause.

## Directory layout

```
inventory-reconciliation-agent/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── src/reconciler/
│   ├── __init__.py
│   ├── models.py            # Pydantic schemas + the refusal invariant validator
│   ├── config.py            # pydantic-settings: thresholds, weights, timeouts
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py          # Source protocol (async query)
│   │   └── simulated.py     # deterministic chaos injection
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── freshness.py     # 2^(-age/H) + hard cutoff
│   │   ├── latency.py       # EWMA baseline + health
│   │   ├── reliability.py   # Wilson lower bound
│   │   ├── consensus.py     # corroboration + cluster + decision rule
│   │   └── trust.py         # gated geometric composite
│   ├── circuit_breaker.py   # 3-state breaker
│   ├── state.py             # AgentState
│   ├── agent.py             # the state machine / decision loop
│   ├── narrator.py          # template default + optional guarded LLM
│   └── cli.py               # typer + rich entrypoint
├── scenarios/*.yaml
├── tests/*.py
└── examples/sample_report.json
```

## Non-negotiable invariants (enforce in code AND test)

1. **Refusal is silent on value.** When a SKU's status is `FLAG_CONTRADICTION` or
   `ESCALATE_INSUFFICIENT`, `reconciled_quantity` **must be `None`**. Enforced by a Pydantic
   model validator *and* a hypothesis property test.
2. **Trust ∈ [0, 1]** for all inputs. Property-tested.
3. **The LLM never decides.** No `anthropic` / `instructor` import may appear under
   `scoring/`, `agent.py`, `state.py`, or `consensus.py`. A grep must find none.
4. **No silent stale fill.** The agent never substitutes a last-known or stale value to fill a
   gap. A gap is either reconciled from trusted data or escalated — never quietly patched.
5. **Dynamic query order.** The order sources are queried is computed from observed state.
   There is no hardcoded source sequence, and the agent early-stops when confidence is decisive.
