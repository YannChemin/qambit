"""Tests of qambit.core.plans."""

import json

from qambit.core import plans


def test_load_and_save(tmp_path):
    path = str(tmp_path / "sub" / "modes.json")
    assert plans.load_json_list(path) == []
    modes = []
    plans.add_mode(modes, "Paragliding", 92, 1, 1, 1)
    plans.add_mode(modes, "Running", 3)
    plans.save_json(path, modes)
    assert plans.load_json_list(path) == modes
    assert [m["CustomModeID"] for m in modes] == [1, 2]
    # No temporary file is left behind.
    assert sorted(p.name for p in (tmp_path / "sub").iterdir()) == ["modes.json"]


def test_load_rejects_non_list(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"a": 1}))
    try:
        plans.load_json_list(str(path))
    except ValueError:
        return
    raise AssertionError("a JSON object was accepted")


def test_check_sport_modes():
    modes = []
    assert plans.check_sport_modes(modes)
    plans.add_mode(modes, "Hélicoptère", 1)
    assert plans.check_sport_modes(modes) == []
    modes[0]["GPSInterval"] = 0  # "Best" is allowed.
    assert plans.check_sport_modes(modes) == []
    for i in range(16):
        plans.add_mode(modes, "Mode {}".format(i), 1)
    modes[1]["CustomModeID"] = modes[2]["CustomModeID"]
    modes[3]["Name"] = "Ελλάδα"
    modes[4]["Name"] = " "
    problems = " ".join(plans.check_sport_modes(modes))
    assert "at most 16" in problems
    assert "reuses the id" in problems
    assert "cannot show" in problems
    assert "has no name" in problems


def _plan(steps):
    plan = plans.new_plan("Test")
    entry = plans.new_entry("2026-07-01")
    entry["workout"]["steps"] = steps
    plan["entries"].append(entry)
    return plan


def test_check_plan_ok():
    steps = [
        plans.new_step("warmup", "time", 600),
        {"type": {"typeName": "repeatStart", "value": 4}},
        plans.new_step("interval", "distance", 400),
        plans.new_step("recovery", "lap", 0),
        {"type": {"typeName": "repeatEnd"}},
    ]
    plans.set_target(steps[2], "hr", 150, 170)
    assert plans.check_plan(_plan(steps)) == []
    assert steps[2]["target"] == {"targetName": "hr", "valueRange": {"min": 150, "max": 170}}


def test_check_plan_problems():
    assert plans.check_plan(plans.new_plan())
    nested = [
        {"type": {"typeName": "repeatStart", "value": 2}},
        {"type": {"typeName": "repeatStart", "value": 2}},
        plans.new_step(),
        {"type": {"typeName": "repeatEnd"}},
    ]
    problems = " ".join(plans.check_plan(_plan(nested)))
    assert "nested" in problems and "not closed" in problems
    bad = plans.new_step("interval", "time", 0)
    plans.set_target(bad, "pace", 10, 5)
    problems = " ".join(plans.check_plan(_plan([bad, {"type": {"typeName": "repeatEnd"}}])))
    assert "needs a value" in problems
    assert "min above max" in problems
    assert "no start" in problems
