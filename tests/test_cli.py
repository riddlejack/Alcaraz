from tennislab import cli


def test_reproduce_small_runs() -> None:
    assert cli.main(["reproduce-small"]) == 0


def test_ladder_not_yet_ported_fails_loudly() -> None:
    assert cli.main(["report", "--ladder"]) == 2


def test_chain_commands_are_forwarded_to_the_runner(tmp_path) -> None:
    config = tmp_path / "chain.json"
    config.write_text("{}")
    # An empty chain config has no year_plan: the runner refuses before doing anything.
    import pytest

    from tennislab.chain.common import ChainError

    with pytest.raises(ChainError):
        cli.main(["chain", "dry-run", "--config", str(config)])
