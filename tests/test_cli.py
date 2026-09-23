from tennislab import cli


def test_reproduce_small_runs() -> None:
    assert cli.main(["reproduce-small"]) == 0


def test_report_without_ladder_fails_loudly() -> None:
    assert cli.main(["report"]) == 2


def test_report_run_roots_accumulate_and_options_are_not_abbreviated(monkeypatch) -> None:
    import pytest

    from tennislab.evaluation import ladder

    forwarded: list[list[str]] = []
    monkeypatch.setattr(ladder, "main", lambda argv: forwarded.append(list(argv)) or 0)
    assert cli.main(["report", "--ladder", "--run", "ATP=a", "--run", "WTA=b"]) == 0
    assert cli.main(["report", "--ladder", "--runs", "ATP=a", "--runs", "WTA=b"]) == 0
    assert cli.main(["report", "--ladder", "--runs", "ATP=a", "WTA=b", "--run", "WTA01=c"]) == 0
    assert forwarded == [
        ["--run", "ATP=a", "--run", "WTA=b"],
        ["--run", "ATP=a", "--run", "WTA=b"],
        ["--run", "ATP=a", "--run", "WTA=b", "--run", "WTA01=c"],
    ]
    for abbreviated in (["--ru", "ATP=a"], ["--lad"]):
        with pytest.raises(SystemExit):
            cli.main(["report", "--ladder", *abbreviated])
    assert len(forwarded) == 3


def test_chain_commands_are_forwarded_to_the_runner(tmp_path) -> None:
    config = tmp_path / "chain.json"
    config.write_text("{}")
    # An empty chain config has no year_plan: the runner refuses before doing anything.
    import pytest

    from tennislab.chain.common import ChainError

    with pytest.raises(ChainError):
        cli.main(["chain", "dry-run", "--config", str(config)])
