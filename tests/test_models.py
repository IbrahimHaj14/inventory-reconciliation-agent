import pytest
from pydantic import ValidationError

from reconciler.models import DecisionType, SkuReconciliation


def _reconciliation(
    status: DecisionType, reconciled_quantity: int | None
) -> SkuReconciliation:
    return SkuReconciliation(
        sku="SKU-A",
        status=status,
        reconciled_quantity=reconciled_quantity,
        confidence=0.9,
        support=0.8,
        margin=0.7,
        note="test",
    )


def test_refusal_with_value_raises_validation_error() -> None:
    with pytest.raises(ValidationError, match="INVARIANT VIOLATED"):
        _reconciliation(DecisionType.FLAG_CONTRADICTION, 5)


def test_refusal_without_value_succeeds() -> None:
    result = _reconciliation(DecisionType.FLAG_CONTRADICTION, None)

    assert result.reconciled_quantity is None


def test_reconcile_with_value_succeeds() -> None:
    result = _reconciliation(DecisionType.RECONCILE, 5)

    assert result.reconciled_quantity == 5
