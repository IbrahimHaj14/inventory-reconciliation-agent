from reconciler.scoring.latency import LatencyTracker


def test_latency_tracker_known_values() -> None:
    tracker = LatencyTracker()
    tracker.observe(0.3)
    tracker.observe(0.3)

    assert tracker.health(0.3) == 1.0
    assert tracker.health(0.6) == 0.5
