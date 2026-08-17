import math
from dataclasses import dataclass


def corroboration(value: float, consensus: float, scale: float) -> float:
    return math.exp(-abs(value - consensus) / max(scale, 1e-9))


@dataclass(frozen=True)
class Reconciliation:
    value: int | None
    status: str
    support: float
    margin: float
    confidence: float


def reconcile(
    candidates: list[tuple[int, float]],
    total_expected_trust: float,
    tol: int,
    k_high: float,
    m_min: float,
    support_min: float,
) -> Reconciliation:
    usable = [(value, trust) for value, trust in candidates if trust > 0.0]
    if not usable or total_expected_trust <= 0:
        return Reconciliation(None, "ESCALATE_INSUFFICIENT", 0.0, 0.0, 0.0)

    clusters: list[list[float]] = []
    for value, trust in sorted(usable):
        placed = False
        for cluster in clusters:
            if abs(value - cluster[0] / cluster[1]) <= tol:
                cluster[0] += value * trust
                cluster[1] += trust
                placed = True
                break
        if not placed:
            clusters.append([value * trust, trust])

    clusters.sort(key=lambda cluster: cluster[1], reverse=True)
    w_top = clusters[0][1]
    w_2nd = clusters[1][1] if len(clusters) > 1 else 0.0

    support = min(1.0, w_top / total_expected_trust)
    margin = (w_top - w_2nd) / (w_top + w_2nd) if (w_top + w_2nd) else 1.0
    confidence = support * margin
    value = round(clusters[0][0] / w_top)

    if margin < m_min:
        return Reconciliation(None, "FLAG_CONTRADICTION", support, margin, confidence)
    if support < support_min:
        return Reconciliation(None, "ESCALATE_INSUFFICIENT", support, margin, confidence)
    return Reconciliation(value, "RECONCILE", support, margin, confidence)
