from datetime import UTC, datetime

import pytest

from reconciler.models import DecisionType, ReconciliationReport, SkuReconciliation
from reconciler.narrator import render_narrative, render_template


def _contradiction_report() -> ReconciliationReport:
    return ReconciliationReport(
        generated_at=datetime(2026, 8, 17, tzinfo=UTC),
        scenario="contradiction",
        skus=[
            SkuReconciliation(
                sku="SKU-A",
                status=DecisionType.FLAG_CONTRADICTION,
                reconciled_quantity=None,
                confidence=0.2,
                support=0.6,
                margin=0.1,
                note="Conflicting trusted readings.",
            )
        ],
        overall_note="Operator review required.",
    )


def test_template_explicitly_refuses_without_printing_quantity() -> None:
    narrative = render_template(_contradiction_report())

    assert "SKU-A" in narrative
    assert "REFUSED" in narrative
    assert "quantity=" not in narrative


def test_narrative_falls_back_to_template_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = _contradiction_report()

    assert render_narrative(report) == render_template(report)
