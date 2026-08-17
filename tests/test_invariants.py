from hypothesis import given
from hypothesis import strategies as st

from reconciler.scoring.consensus import reconcile
from reconciler.scoring.freshness import freshness
from reconciler.scoring.reliability import wilson_lower_bound
from reconciler.scoring.trust import geometric_trust

_NORMALIZED_FLOATS = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)
_POSITIVE_WEIGHTS = st.floats(
    min_value=0.001,
    max_value=10.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
)
_SUCCESS_CASES = st.integers(min_value=1, max_value=10_000).flatmap(
    lambda n: st.tuples(st.just(n), st.integers(min_value=0, max_value=n))
)


@given(
    factors=st.lists(
        st.tuples(_NORMALIZED_FLOATS, _POSITIVE_WEIGHTS),
        min_size=1,
        max_size=8,
    )
)
def test_geometric_trust_is_bounded(factors: list[tuple[float, float]]) -> None:
    trust = geometric_trust(factors, gate=1.0)

    assert 0.0 <= trust <= 1.0
    assert geometric_trust(factors, gate=0.0) == 0.0


@given(case=_SUCCESS_CASES)
def test_wilson_lower_bound_is_bounded_and_success_monotonic(
    case: tuple[int, int],
) -> None:
    observations, successes = case
    failures = observations - successes
    current = wilson_lower_bound(successes, failures)
    after_success = wilson_lower_bound(successes + 1, failures)

    assert 0.0 <= current <= 1.0
    assert 0.0 <= after_success <= 1.0
    assert after_success >= current


@given(
    age_s=st.floats(
        min_value=0.0,
        max_value=1_000_000.0,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
    older_by_s=st.floats(
        min_value=0.0,
        max_value=1_000_000.0,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
    half_life_s=st.floats(
        min_value=0.001,
        max_value=1_000_000.0,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
)
def test_freshness_is_bounded_and_non_increasing(
    age_s: float,
    older_by_s: float,
    half_life_s: float,
) -> None:
    current = freshness(age_s, half_life_s)
    older = freshness(age_s + older_by_s, half_life_s)

    assert 0.0 <= current <= 1.0
    assert 0.0 <= older <= 1.0
    assert older <= current


@given(
    candidates=st.lists(
        st.tuples(
            st.integers(min_value=-10_000, max_value=10_000),
            _NORMALIZED_FLOATS,
        ),
        max_size=8,
    ),
    total_expected_trust=st.floats(
        min_value=0.0,
        max_value=10.0,
        allow_nan=False,
        allow_infinity=False,
        allow_subnormal=False,
    ),
    tolerance=st.integers(min_value=0, max_value=100),
    kappa_high=_NORMALIZED_FLOATS,
    margin_min=_NORMALIZED_FLOATS,
    support_min=_NORMALIZED_FLOATS,
)
def test_reconciliation_refusal_never_carries_a_value(
    candidates: list[tuple[int, float]],
    total_expected_trust: float,
    tolerance: int,
    kappa_high: float,
    margin_min: float,
    support_min: float,
) -> None:
    result = reconcile(
        candidates,
        total_expected_trust,
        tolerance,
        kappa_high,
        margin_min,
        support_min,
    )

    if result.status in {"FLAG_CONTRADICTION", "ESCALATE_INSUFFICIENT"}:
        assert result.value is None
    else:
        assert result.status == "RECONCILE"
        assert result.value is not None
