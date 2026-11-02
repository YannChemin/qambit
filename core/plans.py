"""
MODULE:    qambit.core.plans
AUTHOR(S): Yann Chemin
PURPOSE:   Reads, checks and writes the sport modes and training plans that
           openambit2 keeps in ~/.openambit (sport_modes.json and
           training_plans.json), the files openambit-cli writes to the watch.
SPDX-License-Identifier: Unlicense
"""

import json
import os
import tempfile

from .activity import WATCH_NAME_LENGTH, make_mode

# The Ambit keeps at most this many custom sport modes.
MAX_SPORT_MODES = 16

DURATIONS = ("time", "distance", "ascent", "lap", "energy", "hr_below", "hr_above")
# Unit of each duration value, for the editors.
DURATION_UNITS = {
    "time": "s",
    "distance": "m",
    "ascent": "m",
    "lap": "",
    "energy": "kcal",
    "hr_below": "bpm",
    "hr_above": "bpm",
}
TARGETS = ("none", "hr", "pace", "speed", "vertical_speed", "power", "cadence")
STEP_TYPES = ("warmup", "interval", "recovery", "cooldown", "repeatStart", "repeatEnd")


def load_json_list(path):
    """
    A JSON list file, or an empty list when the file does not exist.

    :raises ValueError: When the file is not a JSON list
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("{} does not hold a JSON list".format(path))
    return data


def save_json(path, data):
    """Writes JSON atomically, in the 4-space layout openambit2 uses."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def next_custom_mode_id(modes):
    return max((m.get("CustomModeID", 0) for m in modes), default=0) + 1


def add_mode(modes, name, activity_id, gps_interval=1, recording_interval=1, alti_baro_mode=0):
    """Appends a new sport mode and returns it."""
    mode = make_mode(
        name,
        activity_id,
        next_custom_mode_id(modes),
        gps_interval,
        recording_interval,
        alti_baro_mode,
    )
    modes.append(mode)
    return mode


def check_sport_modes(modes):
    """
    The problems that stop these sport modes from going to the watch.

    :return: List of messages, empty when the modes can be written
    """
    problems = []
    if not modes:
        problems.append("There is no sport mode to write.")
    if len(modes) > MAX_SPORT_MODES:
        problems.append(
            "The watch holds at most {} sport modes; there are {}.".format(
                MAX_SPORT_MODES, len(modes)
            )
        )
    seen = set()
    for i, mode in enumerate(modes, 1):
        name = mode.get("Name", "")
        if not name.strip():
            problems.append("Sport mode {} has no name.".format(i))
        elif len(name) > WATCH_NAME_LENGTH:
            problems.append(
                "The name {!r} is longer than {} characters.".format(name, WATCH_NAME_LENGTH)
            )
        try:
            # openambit2 sends the name to the watch in Latin-1.
            name.encode("latin-1")
        except UnicodeEncodeError:
            problems.append("The name {!r} has characters the watch cannot show.".format(name))
        mode_id = mode.get("CustomModeID")
        if mode_id in seen:
            problems.append("Sport mode {!r} reuses the id {}.".format(name, mode_id))
        seen.add(mode_id)
        # A GPS interval of 0 is the watch's "best" setting.
        if int(mode.get("GPSInterval", 1)) < 0:
            problems.append("GPSInterval of {!r} cannot be negative.".format(name))
        if int(mode.get("RecordingInterval", 1)) < 1:
            problems.append("RecordingInterval of {!r} must be at least 1 s.".format(name))
    return problems


def new_step(type_name="interval", duration="time", value=60):
    return {
        "type": {"typeName": type_name},
        "duration": {"durationName": duration, "value": value},
        "target": {"targetName": "none"},
        "notify": {"beep": True, "light": True},
    }


def new_plan(name="Training plan"):
    return {"name": name, "entries": []}


def new_entry(date_iso, workout_name="Workout"):
    return {"date": date_iso, "workout": {"name": workout_name, "steps": [new_step()]}}


def set_target(step, target_name, low=0, high=0):
    step["target"] = {"targetName": target_name}
    if target_name != "none":
        step["target"]["valueRange"] = {"min": int(low), "max": int(high)}


def check_plan(plan):
    """
    The problems that stop a training plan from going to the watch, following
    the rules of openambit2's App Zone generator (src/movescount/workout.cpp).

    :return: List of messages, empty when the plan can be written
    """
    problems = []
    entries = plan.get("entries", [])
    if not entries:
        problems.append("The plan {!r} has no workout.".format(plan.get("name", "")))
    for entry in entries:
        workout = entry.get("workout", {})
        label = "{} {}".format(entry.get("date", "?"), workout.get("name", ""))
        steps = workout.get("steps", [])
        real = [s for s in steps if s["type"]["typeName"] not in ("repeatStart", "repeatEnd")]
        if not real:
            problems.append("{}: the workout has no step.".format(label))
        depth = 0
        for step in steps:
            kind = step["type"]["typeName"]
            if kind == "repeatStart":
                depth += 1
                if depth > 1:
                    problems.append("{}: repeats cannot be nested.".format(label))
                if int(step["type"].get("value", 0)) < 1:
                    problems.append("{}: a repeat needs a count of at least 1.".format(label))
            elif kind == "repeatEnd":
                depth -= 1
                if depth < 0:
                    problems.append("{}: a repeat end has no start.".format(label))
                    depth = 0
            else:
                duration = step["duration"]["durationName"]
                if duration not in DURATIONS:
                    problems.append("{}: unknown duration {!r}.".format(label, duration))
                elif duration != "lap" and int(step["duration"].get("value", 0)) <= 0:
                    problems.append("{}: a {} step needs a value.".format(label, duration))
                target = step.get("target", {})
                if target.get("targetName", "none") != "none":
                    rng = target.get("valueRange", {})
                    if int(rng.get("min", 0)) > int(rng.get("max", 0)):
                        problems.append("{}: a target range has min above max.".format(label))
        if depth > 0:
            problems.append("{}: a repeat is not closed.".format(label))
    return problems
