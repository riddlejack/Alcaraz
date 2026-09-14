from tennislab import cli


def test_reproduce_small_runs() -> None:
    assert cli.main(["reproduce-small"]) == 0


def test_unported_commands_fail_loudly() -> None:
    assert cli.main(["fit"]) == 2
