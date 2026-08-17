import pytest

from reconciler.scoring.trust import geometric_trust


def test_geometric_trust_known_values() -> None:
    trust = geometric_trust([(0.9, 1), (0.9, 1)], 1.0)

    assert trust == pytest.approx(0.9)


def test_near_zero_factor_collapses_geometric_trust() -> None:
    trust = geometric_trust([(0.9, 1), (0.0, 1)], 1.0)

    assert trust < 0.001


def test_zero_gate_returns_zero() -> None:
    assert geometric_trust([(0.9, 1), (0.9, 1)], 0.0) == 0.0
