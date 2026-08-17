from reconciler.scoring.consensus import reconcile


def test_reconcile_agreeing_high_trust_values() -> None:
    result = reconcile(
        candidates=[(412, 0.9), (411, 0.9)],
        total_expected_trust=3.0,
        tol=2,
        k_high=0.6,
        m_min=0.34,
        support_min=0.4,
    )

    assert result.status == "RECONCILE"
    assert result.value == 412


def test_reconcile_far_apart_high_trust_values() -> None:
    result = reconcile(
        candidates=[(412, 0.9), (999, 0.9)],
        total_expected_trust=3.0,
        tol=2,
        k_high=0.6,
        m_min=0.34,
        support_min=0.4,
    )

    assert result.status == "FLAG_CONTRADICTION"
    assert result.value is None


def test_reconcile_all_zero_trust_values() -> None:
    result = reconcile(
        candidates=[(412, 0.0), (411, 0.0)],
        total_expected_trust=3.0,
        tol=2,
        k_high=0.6,
        m_min=0.34,
        support_min=0.4,
    )

    assert result.status == "ESCALATE_INSUFFICIENT"
    assert result.value is None
