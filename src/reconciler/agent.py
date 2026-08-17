import asyncio
from dataclasses import dataclass
from datetime import datetime

from reconciler.circuit_breaker import BreakerState, CircuitBreaker
from reconciler.config import Settings
from reconciler.models import (
    DecisionRecord,
    DecisionType,
    QueryOutcome,
    ReconciliationReport,
    SkuReconciliation,
    SourceHealth,
    SourceName,
    SourceQueryResult,
)
from reconciler.scoring.consensus import Reconciliation, corroboration, reconcile
from reconciler.scoring.freshness import freshness
from reconciler.scoring.latency import LatencyTracker
from reconciler.scoring.reliability import wilson_lower_bound
from reconciler.scoring.trust import geometric_trust
from reconciler.sources.simulated import ScenarioSpec, SourceSpec, build_sources
from reconciler.state import AgentState, SourceRuntime

Candidate = tuple[int, float, SourceName]


@dataclass(frozen=True)
class _Metrics:
    age_s: float | None
    baseline_s: float | None
    freshness: float
    latency_health: float
    reliability: float
    trust: float
    gate: float


def _append_once(items: list[SourceName], source: SourceName) -> None:
    if source not in items:
        items.append(source)


def _log(
    state: AgentState,
    now: datetime,
    decision: DecisionType,
    subject: str,
    rationale: str,
    evidence: dict[str, float],
) -> None:
    state.log(
        DecisionRecord(
            step=0,
            decision=decision,
            subject=subject,
            rationale=rationale,
            evidence=evidence,
            timestamp=now,
        )
    )


def _source_priority(
    source: SourceName,
    source_spec: SourceSpec,
    runtime: SourceRuntime,
    breaker: CircuitBreaker,
    settings: Settings,
) -> float:
    expected_freshness = freshness(
        source_spec.age_s,
        settings.freshness_half_life_s,
        settings.freshness_cutoff_s,
    )
    prior_reliability = wilson_lower_bound(
        runtime.successes,
        runtime.failures,
        settings.wilson_z,
    )
    gate = 0.0 if breaker.state is BreakerState.OPEN else 1.0
    return geometric_trust(
        [
            (expected_freshness, settings.w_freshness),
            (prior_reliability, settings.w_reliability),
        ],
        gate,
    )


def _assess_result(
    result: SourceQueryResult,
    runtime: SourceRuntime,
    latency_tracker: LatencyTracker,
    settings: Settings,
    now: datetime,
) -> tuple[SourceQueryResult, _Metrics]:
    assessed_result = result
    age_s: float | None = None
    if result.data_timestamp is not None:
        try:
            age_s = (now - result.data_timestamp).total_seconds()
        except (TypeError, ValueError):
            assessed_result = result.model_copy(
                update={"outcome": QueryOutcome.INVALID, "error": "malformed timestamp"}
            )

    if assessed_result.outcome is QueryOutcome.OK and (age_s is None or age_s < 0.0):
        assessed_result = assessed_result.model_copy(
            update={"outcome": QueryOutcome.INVALID, "error": "missing or future timestamp"}
        )
    if assessed_result.latency_s < 0.0:
        assessed_result = assessed_result.model_copy(
            update={"outcome": QueryOutcome.INVALID, "error": "negative latency"}
        )

    freshness_score = (
        freshness(age_s, settings.freshness_half_life_s, settings.freshness_cutoff_s)
        if age_s is not None
        else 0.0
    )
    baseline_s = latency_tracker.ewma
    if assessed_result.latency_s < 0.0:
        latency_health = 0.0
    else:
        latency_health = max(0.0, min(1.0, latency_tracker.health(assessed_result.latency_s)))
        latency_tracker.observe(assessed_result.latency_s)
    reliability = wilson_lower_bound(
        runtime.successes,
        runtime.failures,
        settings.wilson_z,
    )
    gate = 1.0 if assessed_result.outcome is QueryOutcome.OK and freshness_score > 0.0 else 0.0
    trust = geometric_trust(
        [
            (freshness_score, settings.w_freshness),
            (latency_health, settings.w_latency),
            (reliability, settings.w_reliability),
        ],
        gate,
    )
    return assessed_result, _Metrics(
        age_s=age_s,
        baseline_s=baseline_s,
        freshness=freshness_score,
        latency_health=latency_health,
        reliability=reliability,
        trust=trust,
        gate=gate,
    )


def _metrics_evidence(metrics: _Metrics, latency_s: float, priority: float) -> dict[str, float]:
    evidence = {
        "latency_s": latency_s,
        "freshness": metrics.freshness,
        "latency_health": metrics.latency_health,
        "reliability": metrics.reliability,
        "trust": metrics.trust,
        "priority": priority,
    }
    if metrics.age_s is not None:
        evidence["age_s"] = metrics.age_s
    if metrics.baseline_s is not None:
        evidence["baseline_s"] = metrics.baseline_s
    return evidence


def _health_reason(result: SourceQueryResult, metrics: _Metrics) -> str:
    age = "unknown" if metrics.age_s is None else f"{metrics.age_s:.3f}s"
    if metrics.gate > 0.0:
        return (
            f"Accepted {result.source.value}: age={age}, latency={result.latency_s:.3f}s, "
            f"intrinsic trust={metrics.trust:.3f}."
        )
    return (
        f"Rejected {result.source.value}: outcome={result.outcome.value}, age={age}, "
        f"latency={result.latency_s:.3f}s, intrinsic trust={metrics.trust:.3f}."
    )


def _provisional_reconciliations(
    state: AgentState,
    skus: list[str],
    total_expected_trust: float,
    settings: Settings,
) -> dict[str, Reconciliation]:
    return {
        sku: reconcile(
            [(value, trust) for value, trust, _ in state.candidates.get(sku, [])],
            total_expected_trust=total_expected_trust,
            tol=settings.cluster_tolerance,
            k_high=settings.kappa_high,
            m_min=settings.margin_min,
            support_min=settings.support_min,
        )
        for sku in skus
    }


def _all_decisive(
    state: AgentState,
    provisional: dict[str, Reconciliation],
    settings: Settings,
) -> bool:
    if not provisional:
        return False
    for sku, result in provisional.items():
        trusted_sources = {
            source for _, trust, source in state.candidates.get(sku, []) if trust > 0.0
        }
        if (
            len(trusted_sources) <= 1
            or result.status != "RECONCILE"
            or result.confidence < settings.kappa_high
            or result.margin < settings.margin_min
        ):
            return False
    return True


def _candidate_reference(
    final_result: Reconciliation,
    provisional_result: Reconciliation,
    candidates: list[Candidate],
) -> int | None:
    if final_result.value is not None:
        return final_result.value
    if provisional_result.value is not None:
        return provisional_result.value
    usable = [candidate for candidate in candidates if candidate[1] > 0.0]
    if not usable:
        return None
    return max(usable, key=lambda candidate: candidate[1])[0]


def _classify_sources(
    candidates: list[Candidate],
    reference: int | None,
    tolerance: int,
) -> tuple[list[SourceName], list[SourceName]]:
    contributing: list[SourceName] = []
    distrusted: list[SourceName] = []
    for value, trust, source in candidates:
        if source in contributing or source in distrusted:
            continue
        if trust <= 0.0 or reference is None or abs(value - reference) > tolerance:
            distrusted.append(source)
        else:
            contributing.append(source)
    return contributing, distrusted


def _result_note(status: DecisionType) -> str:
    if status is DecisionType.RECONCILE:
        return "Reconciled from trusted source agreement."
    if status is DecisionType.FLAG_CONTRADICTION:
        return "Refused because trusted sources remain contradictory."
    return "Refused because trusted evidence is insufficient."


def _finalize_skus(
    state: AgentState,
    spec: ScenarioSpec,
    settings: Settings,
) -> list[SkuReconciliation]:
    total_expected_trust = float(len(spec.sources))
    provisional = _provisional_reconciliations(
        state,
        spec.skus,
        total_expected_trust,
        settings,
    )
    final_candidates: dict[str, list[Candidate]] = {sku: [] for sku in spec.skus}
    source_corroborations: dict[SourceName, list[float]] = {source: [] for source in spec.sources}
    source_trusts: dict[SourceName, list[float]] = {source: [] for source in spec.sources}

    for sku in spec.skus:
        consensus = provisional[sku].value
        for value, intrinsic_trust, source in state.candidates.get(sku, []):
            health = state.runtime[source].health
            if health is None:
                continue
            corroboration_score = (
                1.0
                if consensus is None
                else corroboration(value, consensus, settings.corroboration_scale)
            )
            gate = 1.0 if intrinsic_trust > 0.0 else 0.0
            final_trust = geometric_trust(
                [
                    (health.freshness, settings.w_freshness),
                    (health.latency_health, settings.w_latency),
                    (health.reliability, settings.w_reliability),
                    (corroboration_score, settings.w_corroboration),
                ],
                gate,
            )
            final_candidates[sku].append((value, final_trust, source))
            source_corroborations[source].append(corroboration_score)
            source_trusts[source].append(final_trust)

    for source, runtime in state.runtime.items():
        if runtime.health is None:
            continue
        corroboration_values = source_corroborations[source]
        trust_values = source_trusts[source]
        corroboration_score = (
            sum(corroboration_values) / len(corroboration_values) if corroboration_values else 1.0
        )
        if trust_values:
            final_trust = sum(trust_values) / len(trust_values)
        else:
            gate = 1.0 if runtime.health.trust > 0.0 else 0.0
            final_trust = geometric_trust(
                [
                    (runtime.health.freshness, settings.w_freshness),
                    (runtime.health.latency_health, settings.w_latency),
                    (runtime.health.reliability, settings.w_reliability),
                    (corroboration_score, settings.w_corroboration),
                ],
                gate,
            )
        runtime.health = runtime.health.model_copy(
            update={"corroboration": corroboration_score, "trust": final_trust}
        )

    sku_results: list[SkuReconciliation] = []
    for sku in spec.skus:
        result = reconcile(
            [(value, trust) for value, trust, _ in final_candidates[sku]],
            total_expected_trust=total_expected_trust,
            tol=settings.cluster_tolerance,
            k_high=settings.kappa_high,
            m_min=settings.margin_min,
            support_min=settings.support_min,
        )
        status = DecisionType(result.status.lower())
        reference = _candidate_reference(result, provisional[sku], final_candidates[sku])
        contributing, distrusted = _classify_sources(
            final_candidates[sku],
            reference,
            settings.cluster_tolerance,
        )
        sku_results.append(
            SkuReconciliation(
                sku=sku,
                status=status,
                reconciled_quantity=result.value,
                confidence=result.confidence,
                support=result.support,
                margin=result.margin,
                contributing_sources=contributing,
                distrusted_sources=distrusted,
                note=_result_note(status),
            )
        )
    return sku_results


async def run_agent(
    spec: ScenarioSpec,
    settings: Settings,
    now: datetime,
) -> ReconciliationReport:
    sources = {source.name: source for source in build_sources(spec, now)}
    state = AgentState(
        runtime={source: SourceRuntime() for source in spec.sources},
        candidates={sku: [] for sku in spec.skus},
    )
    breakers = {
        source: CircuitBreaker(
            failure_threshold=settings.breaker_failure_threshold,
            cooldown_s=settings.breaker_cooldown_s,
        )
        for source in spec.sources
    }
    attempts = {source: 0 for source in spec.sources}
    pending = set(spec.sources)
    latency_tracker = LatencyTracker(settings.latency_ewma_alpha)
    run_time_s = now.timestamp()
    early_stopped = False

    while pending:
        blocked = [source for source in pending if not breakers[source].allow(run_time_s)]
        for source in sorted(blocked, key=lambda item: item.value):
            pending.remove(source)
            _append_once(state.skipped, source)
            _log(
                state,
                now,
                DecisionType.SKIP,
                source.value,
                f"Skipped {source.value} because its circuit breaker is open.",
                {"failures": float(state.runtime[source].failures)},
            )
        if not pending:
            break

        priorities = {
            source: _source_priority(
                source,
                spec.sources[source],
                state.runtime[source],
                breakers[source],
                settings,
            )
            for source in pending
        }
        selected = max(pending, key=lambda source: (priorities[source], source.value))
        priority = priorities[selected]
        attempts[selected] += 1
        _append_once(state.queried, selected)

        try:
            result = await asyncio.wait_for(
                sources[selected].query(spec.skus),
                timeout=settings.query_timeout_s,
            )
        except TimeoutError:
            result = SourceQueryResult(
                source=selected,
                outcome=QueryOutcome.TIMEOUT,
                latency_s=settings.query_timeout_s,
                error="query exceeded timeout",
            )
        except Exception as exc:
            result = SourceQueryResult(
                source=selected,
                outcome=QueryOutcome.UNAVAILABLE,
                latency_s=0.0,
                error=str(exc) or exc.__class__.__name__,
            )

        runtime = state.runtime[selected]
        result, metrics = _assess_result(result, runtime, latency_tracker, settings, now)
        runtime.last_result = result
        successful = metrics.gate > 0.0
        if successful:
            runtime.successes += 1
            breakers[selected].record_success(run_time_s)
        else:
            runtime.failures += 1
            breakers[selected].record_failure(run_time_s)

        runtime.health = SourceHealth(
            source=selected,
            freshness=metrics.freshness,
            latency_health=metrics.latency_health,
            reliability=metrics.reliability,
            corroboration=1.0,
            trust=metrics.trust,
            circuit_state=breakers[selected].state.value,
            reason=_health_reason(result, metrics),
        )
        for sku in spec.skus:
            state.candidates[sku] = [
                candidate for candidate in state.candidates[sku] if candidate[2] is not selected
            ]
            if sku in result.records:
                state.candidates[sku].append((result.records[sku], metrics.trust, selected))

        _log(
            state,
            now,
            DecisionType.QUERY,
            selected.value,
            runtime.health.reason,
            _metrics_evidence(metrics, result.latency_s, priority),
        )

        if not successful:
            can_retry = attempts[selected] <= settings.max_retries_per_source and breakers[
                selected
            ].allow(run_time_s)
            if can_retry:
                remaining_retries = settings.max_retries_per_source - attempts[selected] + 1
                _log(
                    state,
                    now,
                    DecisionType.RETRY,
                    selected.value,
                    f"Retrying {selected.value} within the configured retry budget.",
                    {
                        "attempt": float(attempts[selected]),
                        "remaining_retries": float(remaining_retries),
                    },
                )
            else:
                pending.remove(selected)
                _append_once(state.skipped, selected)
                _log(
                    state,
                    now,
                    DecisionType.SKIP,
                    selected.value,
                    f"Skipped {selected.value} after its trusted query attempts were exhausted.",
                    {"attempts": float(attempts[selected])},
                )
            continue

        pending.remove(selected)
        provisional = _provisional_reconciliations(
            state,
            spec.skus,
            float(len(state.queried)),
            settings,
        )
        if _all_decisive(state, provisional, settings):
            for source in sorted(pending, key=lambda item: item.value):
                _append_once(state.skipped, source)
                _log(
                    state,
                    now,
                    DecisionType.SKIP,
                    source.value,
                    f"Skipped {source.value} because existing evidence is decisive.",
                    {
                        "confidence": min(result.confidence for result in provisional.values()),
                        "margin": min(result.margin for result in provisional.values()),
                    },
                )
            pending.clear()
            early_stopped = True
            _log(
                state,
                now,
                DecisionType.FINALIZE,
                spec.name,
                (
                    "Finalized early because every SKU crossed the configured confidence "
                    "and margin thresholds."
                ),
                {
                    "queried_sources": float(len(state.queried)),
                    "configured_sources": float(len(spec.sources)),
                },
            )
            break

        if pending:
            contradiction_detected = any(
                result.status == "FLAG_CONTRADICTION" for result in provisional.values()
            )
            rationale = (
                "Contradictory evidence requires another source as a tie-breaker."
                if contradiction_detected
                else "Current confidence is insufficient, so another source will be queried."
            )
            _log(
                state,
                now,
                DecisionType.QUERY,
                spec.name,
                rationale,
                {
                    "confidence": min(result.confidence for result in provisional.values()),
                    "margin": min(result.margin for result in provisional.values()),
                },
            )

    if not early_stopped:
        _log(
            state,
            now,
            DecisionType.FINALIZE,
            spec.name,
            "Finalized after all eligible source queries and retries were exhausted.",
            {
                "queried_sources": float(len(state.queried)),
                "configured_sources": float(len(spec.sources)),
            },
        )

    sku_results = _finalize_skus(state, spec, settings)
    source_health: list[SourceHealth] = []
    for source in spec.sources:
        health = state.runtime[source].health
        if health is not None:
            source_health.append(health)
    return ReconciliationReport(
        generated_at=now,
        scenario=spec.name,
        sources_queried=state.queried,
        sources_skipped=state.skipped,
        source_health=source_health,
        decision_log=state.decisions,
        skus=sku_results,
        overall_note=(
            "Finalized early after decisive multi-source evidence."
            if early_stopped
            else "Finalized after exhausting eligible source evidence."
        ),
    )
