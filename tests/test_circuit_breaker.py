from reconciler.circuit_breaker import BreakerState, CircuitBreaker


def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_s=30.0)

    breaker.record_failure(now=0.0)
    breaker.record_failure(now=1.0)
    assert breaker.state is BreakerState.CLOSED

    breaker.record_failure(now=2.0)
    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow(now=31.0)

    assert breaker.allow(now=32.0)
    assert breaker.state is BreakerState.HALF_OPEN

    breaker.record_success(now=32.0)
    assert breaker.state is BreakerState.CLOSED


def test_half_open_failure_reopens_circuit_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_s=30.0)
    breaker.record_failure(now=0.0)
    assert breaker.allow(now=30.0)
    assert breaker.state is BreakerState.HALF_OPEN

    breaker.record_failure(now=30.0)

    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow(now=59.0)
