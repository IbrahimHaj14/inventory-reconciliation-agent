from reconciler.scoring.reliability import wilson_lower_bound


def test_wilson_lower_bound_neutral_prior() -> None:
    assert wilson_lower_bound(0, 0) == 0.5


def test_wilson_lower_bound_rewards_more_evidence() -> None:
    two_successes = wilson_lower_bound(2, 0)
    ten_successes = wilson_lower_bound(10, 0)

    assert two_successes < 1.0
    assert ten_successes > two_successes
