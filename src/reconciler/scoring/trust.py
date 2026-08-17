import math


def geometric_trust(factors: list[tuple[float, float]], gate: float) -> float:
    """Calculate a gated weighted geometric mean for normalized factors."""
    den = sum(weight for _, weight in factors)
    if den <= 0:
        return 0.0
    num = sum(weight * math.log(max(value, 1e-9)) for value, weight in factors)
    return max(0.0, min(1.0, gate * math.exp(num / den)))
