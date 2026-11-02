"""
MODULE:    qambit.core.cli
AUTHOR(S): Yann Chemin
PURPOSE:   Runs openambit-cli, the command line program of openambit2, which
           does all the talking to the watch.
SPDX-License-Identifier: Unlicense

The plugin needs the offline options of openambit2's openambit-cli
(--info-json, --orbit-file, --sport-modes, --training-plan); the
Movescount-era options are always switched off, since that service is gone.
"""

import json
import os
import shutil
import subprocess

REQUIRED_OPTION = "--info-json"

# Turns off reading logs (-r), time (-t), Movescount orbit (-o), navigation
# (-n), sport modes (-s) and log upload (-l); each operation adds back what
# it needs.
_ALL_OFF = ["-r", "-t", "-o", "-n", "-s", "-l"]


def candidate_paths():
    """Where openambit-cli is looked for, most specific first."""
    return [
        os.path.expanduser("~/dev/openambit2/build/src/openambit-cli/openambit-cli"),
        shutil.which("openambit-cli") or "",
        "/usr/bin/openambit-cli",
        "/usr/local/bin/openambit-cli",
    ]


def supports_offline_options(path):
    """True if this openambit-cli has the options the plugin needs."""
    try:
        out = subprocess.run([path, "--help"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return REQUIRED_OPTION in out


def find_cli(configured=""):
    """
    Path of a usable openambit-cli.

    :param configured: Path set in the plugin options, if any
    :raises FileNotFoundError: When no openambit-cli has the offline options
    """
    paths = [configured] if configured else candidate_paths()
    for path in paths:
        if path and os.access(path, os.X_OK) and supports_offline_options(path):
            return path
    raise FileNotFoundError(
        "No openambit-cli with the {} option was found ({}). Build openambit2 "
        "(~/dev/openambit2) or set its path in the QAmbit options.".format(
            REQUIRED_OPTION, configured or ", ".join(p for p in paths if p)
        )
    )


def sync_args(read_logs=True, sync_time=True, orbit_file=None):
    """Arguments of a sync: logs into ~/.openambit, time, GPS orbit."""
    args = list(_ALL_OFF)
    if read_logs:
        args.remove("-r")
    if sync_time:
        args.remove("-t")
    if orbit_file:
        args += ["--orbit-file", orbit_file]
    return args


def info_args():
    return _ALL_OFF + ["--info-json"]


def sport_modes_args(json_file):
    return _ALL_OFF + ["--sport-modes", json_file]


def training_plan_args(json_file):
    return _ALL_OFF + ["--training-plan", json_file]


class OutputParser:
    """Follows the output of openambit-cli, one line at a time."""

    def __init__(self):
        self.info = None
        self.errors = []
        self.done = []
        self.stored_logs = 0
        self.progress = None  # (current, count, percent of the current log)

    def feed(self, line):
        """
        Reads one output line.

        :return: Overall progress in percent if the line moved it, else None
        """
        line = line.strip()
        if line.startswith("INFO "):
            try:
                self.info = json.loads(line[5:])
            except ValueError:
                self.errors.append("Unreadable device information: " + line)
        elif line.startswith("PROGRESS "):
            try:
                current, count, percent = (int(v) for v in line.split()[1:4])
            except ValueError:
                return None
            self.progress = (current, count, percent)
            if count > 0:
                return min(100.0, 100.0 * (max(current - 1, 0) + percent / 100.0) / count)
        elif line.startswith("DONE "):
            self.done.append(line[5:])
        elif line.startswith("Storing log entry"):
            self.stored_logs += 1
        elif line.startswith("ERROR"):
            message = line.partition(":")[2].strip() or line
            if message != "Exiting":
                self.errors.append(message)
        return None
