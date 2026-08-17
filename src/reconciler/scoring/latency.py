class LatencyTracker:
    def __init__(self, alpha: float = 0.3) -> None:
        self.alpha = alpha
        self.ewma: float | None = None

    def observe(self, latency_s: float) -> None:
        self.ewma = (
            latency_s
            if self.ewma is None
            else self.alpha * latency_s + (1 - self.alpha) * self.ewma
        )

    def health(self, latency_s: float) -> float:
        if not self.ewma:
            return 1.0
        return min(1.0, self.ewma / max(latency_s, 1e-9))
