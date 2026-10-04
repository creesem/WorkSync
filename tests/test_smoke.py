import worksync


def test_version_is_exposed() -> None:
    assert worksync.__version__
