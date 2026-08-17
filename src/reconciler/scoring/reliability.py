import math


def wilson_lower_bound(successes: int, failures: int, z: float = 1.28) -> float:
    n = successes + failures
    if n == 0:
        return 0.5
    p = successes / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    return max(0.0, min(1.0, (centre - margin) / denom))
