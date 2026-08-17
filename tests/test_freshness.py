from reconciler.scoring.freshness import freshness


def test_freshness_known_values() -> None:
    assert freshness(0, 120) == 1.0
    assert freshness(120, 120) == 0.5
    assert freshness(2000, 120, cutoff_s=1800) == 0.0
    assert freshness(-1, 120) == 0.0
