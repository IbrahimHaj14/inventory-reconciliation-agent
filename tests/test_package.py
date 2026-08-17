import reconciler


def test_package_version() -> None:
    assert reconciler.__version__ == "0.1.0"
