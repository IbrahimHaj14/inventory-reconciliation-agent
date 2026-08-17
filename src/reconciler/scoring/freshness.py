def freshness(age_s: float, half_life_s: float, cutoff_s: float | None = None) -> float:
    if age_s < 0:
        return 0.0
    if cutoff_s is not None and age_s > cutoff_s:
        return 0.0
    return 2 ** (-age_s / half_life_s)
