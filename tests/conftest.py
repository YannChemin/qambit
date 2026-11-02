"""
MODULE:    qambit tests
AUTHOR(S): Yann Chemin
PURPOSE:   Makes the plugin importable as the "qambit" package and provides
           the shared fixtures.
SPDX-License-Identifier: Unlicense
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The plugin folder is the package, so its parent goes on the path.
sys.path.insert(0, os.path.dirname(ROOT))
assert os.path.basename(ROOT) == "qambit", "the plugin folder must be named qambit"

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FLIGHT = os.path.join(DATA, "log_TEST000000000001_2026_07_01_10_00_00.log")


@pytest.fixture
def flight_log():
    return FLIGHT


@pytest.fixture(autouse=True)
def metamonitor_spool(tmp_path, monkeypatch):
    """Keeps the tests' progress slots out of the real MetaMonitor spool."""
    monkeypatch.setenv("METAMONITOR_SPOOL", str(tmp_path / "slots"))
