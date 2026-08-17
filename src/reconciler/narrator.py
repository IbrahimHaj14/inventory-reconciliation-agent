import importlib
import os
from typing import Protocol, cast

from reconciler.models import REFUSAL_STATUSES, ReconciliationReport, SourceHealth, SourceName

_NARRATOR_MODEL = "claude-3-5-haiku-latest"
_MAX_NARRATIVE_TOKENS = 1024
_STRICT_SYSTEM_PROMPT = (
    "Rephrase this inventory reconciliation report for an operator. "
    "Do not introduce, remove, infer, or alter any number, source, status, or decision. "
    "A refused SKU must remain refused and must never be assigned a quantity."
)


class _TextBlock(Protocol):
    text: str


class _Message(Protocol):
    content: list[_TextBlock]


class _Messages(Protocol):
    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
    ) -> _Message: ...


class _AnthropicClient(Protocol):
    messages: _Messages


class _AnthropicFactory(Protocol):
    def __call__(self, *, api_key: str) -> _AnthropicClient: ...


def _append_source(sources: list[SourceName], source: SourceName) -> None:
    if source not in sources:
        sources.append(source)


def _ordered_sources(report: ReconciliationReport) -> list[SourceName]:
    sources: list[SourceName] = []
    for source in report.sources_queried:
        _append_source(sources, source)
    for source in report.sources_skipped:
        _append_source(sources, source)
    for health in report.source_health:
        _append_source(sources, health.source)
    for sku in report.skus:
        for source in sku.contributing_sources:
            _append_source(sources, source)
        for source in sku.distrusted_sources:
            _append_source(sources, source)
    return sources


def _source_state(
    source: SourceName,
    report: ReconciliationReport,
    used_sources: set[SourceName],
    distrusted_sources: set[SourceName],
) -> str:
    states: list[str] = []
    if source in used_sources:
        states.append("used")
    if source in distrusted_sources:
        states.append("distrusted")
    if source in report.sources_skipped:
        states.append("skipped")
    if not states and source in report.sources_queried:
        states.append("queried")
    return ", ".join(states) if states else "not queried"


def _render_source(
    source: SourceName,
    state: str,
    health: SourceHealth | None,
) -> str:
    if health is None:
        return f"- {source.value}: {state}; no health sample was collected."
    return (
        f"- {source.value}: {state}; trust={health.trust:.3f}, "
        f"freshness={health.freshness:.3f}, latency_health={health.latency_health:.3f}, "
        f"reliability={health.reliability:.3f}, corroboration={health.corroboration:.3f}, "
        f"circuit={health.circuit_state}. {health.reason}"
    )


def render_template(report: ReconciliationReport) -> str:
    """Render a deterministic narrative using only ground-truth report fields."""
    lines = [
        f"Inventory reconciliation report: {report.scenario}",
        f"Generated at: {report.generated_at.isoformat()}",
        "Sources:",
    ]
    health_by_source = {health.source: health for health in report.source_health}
    used_sources = {
        source for sku in report.skus for source in sku.contributing_sources
    }
    distrusted_sources = {
        source for sku in report.skus for source in sku.distrusted_sources
    }
    for source in _ordered_sources(report):
        state = _source_state(source, report, used_sources, distrusted_sources)
        lines.append(_render_source(source, state, health_by_source.get(source)))

    lines.append("SKUs:")
    for sku in report.skus:
        if sku.status in REFUSAL_STATUSES:
            lines.append(
                f"- {sku.sku}: REFUSED ({sku.status.value}); confidence={sku.confidence:.3f}, "
                f"support={sku.support:.3f}, margin={sku.margin:.3f}. {sku.note}"
            )
        else:
            lines.append(
                f"- {sku.sku}: quantity={sku.reconciled_quantity}; status={sku.status.value}, "
                f"confidence={sku.confidence:.3f}, support={sku.support:.3f}, "
                f"margin={sku.margin:.3f}. {sku.note}"
            )
    if report.overall_note:
        lines.append(f"Overall: {report.overall_note}")
    return "\n".join(lines)


def render_narrative(report: ReconciliationReport) -> str:
    """Optionally rephrase a completed report, with deterministic fallback on any failure."""
    template = render_template(report)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return template

    try:
        anthropic_module = importlib.import_module("anthropic")
        factory = cast(_AnthropicFactory, vars(anthropic_module)["Anthropic"])
        client = factory(api_key=api_key)
        response = client.messages.create(
            model=_NARRATOR_MODEL,
            max_tokens=_MAX_NARRATIVE_TOKENS,
            system=_STRICT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": report.model_dump_json()}],
        )
        narrative = "".join(block.text for block in response.content).strip()
        return narrative or template
    except Exception:
        return template
