"""
MODULE:    qambit.core.mmslot
AUTHOR(S): Yann Chemin
PURPOSE:   Reports the progress of long jobs (watch sync, log import, DEM
           download) to MetaMonitor, https://github.com/YannChemin/MetaMonitor
SPDX-License-Identifier: Unlicense

One JSON slot file per task in $XDG_RUNTIME_DIR/metamonitor/slots, replaced
atomically. Every write is best effort: the job never fails or slows down
because MetaMonitor or its spool is missing.
"""

import json
import os
import time


def _spool():
    spool = os.environ.get("METAMONITOR_SPOOL")
    if spool:
        return spool
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/{}".format(os.getuid())
    return os.path.join(runtime, "metamonitor", "slots")


class Slot:
    """A MetaMonitor progress slot, throttled to about one write per second."""

    def __init__(self, slot_id, name):
        self.slot_id = slot_id
        self.name = name
        self._last = 0.0

    def publish(self, percent=None, detail="", state="running", force=False):
        now = time.monotonic()
        if not force and state == "running" and now - self._last < 1.0:
            return
        self._last = now
        payload = {
            "name": self.name,
            "detail": detail,
            "state": state,
            "pid": os.getpid(),
        }
        if percent is not None:
            payload["percent"] = max(0.0, min(100.0, float(percent)))
        try:
            spool = _spool()
            os.makedirs(spool, exist_ok=True)
            tmp = os.path.join(spool, ".{}.tmp".format(self.slot_id))
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, os.path.join(spool, self.slot_id))
        except OSError:
            pass

    def done(self, detail=""):
        self.publish(100, detail, "done", force=True)

    def fail(self, detail=""):
        self.publish(None, detail, "failed", force=True)
