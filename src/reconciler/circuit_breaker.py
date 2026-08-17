from enum import StrEnum


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_s: float) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> BreakerState:
        return self._state

    def allow(self, now: float) -> bool:
        if self._state is BreakerState.CLOSED:
            return True
        if self._state is BreakerState.HALF_OPEN:
            return True
        if self._opened_at is not None and now - self._opened_at >= self._cooldown_s:
            self._state = BreakerState.HALF_OPEN
            return True
        return False

    def record_success(self, now: float) -> None:
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self, now: float) -> None:
        if self._state is BreakerState.HALF_OPEN:
            self._trip(now)
            return
        if self._state is BreakerState.OPEN:
            self._opened_at = now
            return

        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._trip(now)

    def _trip(self, now: float) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = now
