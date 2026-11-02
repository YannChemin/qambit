"""
MODULE:    qambit.tasks
AUTHOR(S): Yann Chemin
PURPOSE:   Background jobs of the plugin, as QGIS tasks (task manager,
           progress, cancel): talking to the watch through openambit-cli,
           importing logs, fetching the Copernicus DEM, updating the GPS
           orbit file. Each also reports to MetaMonitor,
           https://github.com/YannChemin/MetaMonitor
SPDX-License-Identifier: Unlicense
"""

import subprocess

from qgis.core import QgsTask

from .core import cli, dem, lidarhd, store
from .core.mmslot import Slot


class _Task(QgsTask):
    """A QGIS task calling `on_finished(task, ok)` in the main thread."""

    def __init__(self, description, slot_id, on_finished=None):
        # Default flags: cancelable, hidden-able
        super().__init__(description)
        self.on_finished = on_finished
        self.error = ""
        self.slot = Slot(slot_id, description)

    def report(self, percent, detail=""):
        self.setProgress(percent)
        self.slot.publish(percent, detail)

    def finished(self, ok):
        if ok:
            self.slot.done(self.description())
        else:
            self.slot.fail(self.error or "canceled")
        if self.on_finished:
            self.on_finished(self, ok)


class CliTask(_Task):
    """Runs openambit-cli and follows its output."""

    def __init__(self, description, cli_path, args, on_finished=None):
        super().__init__(description, "qambit-watch", on_finished)
        self.command = [cli_path] + list(args)
        self.output = cli.OutputParser()
        self.log = []

    def run(self):
        try:
            process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
        except OSError as e:
            self.error = str(e)
            return False
        self.report(0, "connecting to the watch")
        for line in process.stdout:
            self.log.append(line.rstrip())
            percent = self.output.feed(line)
            if percent is not None:
                current, count, _ = self.output.progress
                self.report(percent, "log {}/{}".format(current, count))
            if self.isCanceled():
                process.terminate()
                break
        code = process.wait()
        if self.isCanceled():
            return False
        if code != 0 or self.output.errors:
            self.error = "; ".join(
                self.output.errors
            ) or "openambit-cli exited with code {}".format(code)
            return False
        return True


class ImportTask(_Task):
    """Imports log files into the GeoPackage store."""

    def __init__(self, description, paths, gpkg, force=False, on_finished=None):
        super().__init__(description, "qambit-import", on_finished)
        self.paths = paths
        self.gpkg = gpkg
        self.force = force
        self.result = None

    def run(self):
        def progress(done, total, log_id):
            self.report(100.0 * done / max(total, 1), log_id)

        try:
            self.result = store.import_logs(
                self.paths, self.gpkg, progress, self.isCanceled, self.force
            )
        except Exception as e:  # GDAL raises RuntimeError, files OSError
            self.error = str(e)
            return False
        return not self.isCanceled()


class DemTask(_Task):
    """
    Writes the elevation around a box (WGS84 degrees) to a GeoTIFF: IGN
    LiDAR HD in France, the Copernicus DEM elsewhere.
    """

    def __init__(
        self,
        description,
        box,
        cache_dir,
        source="auto",
        product="mns",
        on_finished=None,
    ):
        super().__init__(description, "qambit-dem", on_finished)
        self.box = box
        self.cache_dir = cache_dir
        self.source = source
        self.product = product
        self.path = None
        self.used = None
        self.note = ""

    def run(self):
        def progress(done, total, what):
            self.report(100.0 * done / max(total, 1), what)

        try:
            if self.source in ("auto", "lidarhd"):
                try:
                    self.path = lidarhd.build_lidarhd_dem(
                        *self.box,
                        self.cache_dir,
                        product=self.product,
                        feedback=progress,
                        is_canceled=self.isCanceled,
                    )
                    self.used = "lidarhd"
                    return True
                except (lidarhd.NotCovered, ValueError) as e:
                    if self.source == "lidarhd":
                        raise
                    self.note = str(e)
            self.path = dem.build_copernicus_dem(*self.box, self.cache_dir, feedback=progress)
            self.used = "copernicus"
        except (ValueError, OSError, RuntimeError) as e:
            self.error = str(e)
            return False
        return True


class OrbitTask(_Task):
    """Runs openambit2's rinex2ubx_ambit.py: today's GPS ephemeris, no account."""

    def __init__(self, description, script, output, on_finished=None):
        super().__init__(description, "qambit-orbit", on_finished)
        # Inside QGIS, sys.executable is the QGIS binary
        self.command = ["python3", script, "--output", output]
        self.output = ""

    def run(self):
        self.report(0, "downloading the broadcast ephemeris")
        try:
            done = subprocess.run(self.command, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as e:
            self.error = str(e)
            return False
        self.output = (done.stdout + done.stderr).strip()
        if done.returncode != 0:
            self.error = (
                self.output.splitlines()[-1]
                if self.output
                else "exit code {}".format(done.returncode)
            )
            return False
        return True
