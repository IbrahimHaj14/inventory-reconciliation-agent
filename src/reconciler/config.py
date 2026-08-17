from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REC_", env_file=".env")

    # decision thresholds
    kappa_high: float = 0.6
    margin_min: float = 0.34
    support_min: float = 0.4
    cluster_tolerance: int = 2

    # trust weights (freshness, latency, reliability, corroboration)
    w_freshness: float = 1.0
    w_latency: float = 0.6
    w_reliability: float = 1.0
    w_corroboration: float = 1.2

    # freshness
    freshness_half_life_s: float = 120.0
    freshness_cutoff_s: float = 1800.0

    # latency
    latency_ewma_alpha: float = 0.3

    # reliability
    wilson_z: float = 1.28

    # corroboration scale (tolerance unit for exp decay)
    corroboration_scale: float = 5.0

    # circuit breaker
    breaker_failure_threshold: int = 3
    breaker_cooldown_s: float = 30.0

    # per-source query timeout
    query_timeout_s: float = 2.0

    # retry budget per run
    max_retries_per_source: int = 1


settings = Settings()
