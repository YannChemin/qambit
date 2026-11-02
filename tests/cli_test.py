"""Tests of qambit.core.cli."""

import os
import stat

import pytest

from qambit.core import cli


def test_sync_args():
    args = cli.sync_args(read_logs=True, sync_time=False, orbit_file="/tmp/o.uo")
    # Movescount stays off; logs are read; the time is left alone.
    assert "-r" not in args and "-t" in args
    assert {"-o", "-n", "-s", "-l"} <= set(args)
    assert args[-2:] == ["--orbit-file", "/tmp/o.uo"]
    assert "--orbit-file" not in cli.sync_args()


def test_write_args():
    assert cli.sport_modes_args("m.json")[-2:] == ["--sport-modes", "m.json"]
    assert cli.training_plan_args("p.json")[-2:] == ["--training-plan", "p.json"]
    assert cli.info_args()[-1] == "--info-json"
    # Every call keeps "-s", else openambit-cli needs a Movescount object.
    for args in (cli.sync_args(), cli.info_args(), cli.sport_modes_args("x")):
        assert "-s" in args


def test_output_parser():
    out = cli.OutputParser()
    assert out.feed('INFO {"name": "Ambit3", "charge": 80}\n') is None
    assert out.info == {"name": "Ambit3", "charge": 80}
    assert out.feed("PROGRESS 1 4 50") == pytest.approx(12.5)
    assert out.feed("PROGRESS 4 4 100") == pytest.approx(100.0)
    out.feed("Storing log entry 3/4")
    out.feed("DONE sport-modes 5")
    out.feed("ERROR: No clock found")
    out.feed("ERROR: Exiting")
    assert out.stored_logs == 1
    assert out.done == ["sport-modes 5"]
    assert out.errors == ["No clock found"]


def _fake_cli(path, help_text):
    path.write_text("#!/bin/sh\necho '{}'\n".format(help_text))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_find_cli(tmp_path):
    good = _fake_cli(tmp_path / "good", "--info-json  Print the device info")
    old = _fake_cli(tmp_path / "old", "--help")
    assert cli.find_cli(good) == good
    with pytest.raises(FileNotFoundError):
        cli.find_cli(old)
    with pytest.raises(FileNotFoundError):
        cli.find_cli(os.path.join(str(tmp_path), "missing"))
