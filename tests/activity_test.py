"""Tests of qambit.core.activity."""

import pytest

from qambit.core import activity


@pytest.mark.parametrize(
    "activity_type, name, expected",
    [
        (92, "Paragliding", activity.AIR),
        (1, "Vol en hélicoptère", activity.AIR),
        (1, "Wingsuit", activity.AIR),
        (3, "Running", activity.GROUND),
        (6, "Pool swimming", activity.WATER),
        (1, "Via ferrata", activity.VERTICAL),
        (1, "Scuba diving", activity.UNDERWATER),
    ],
)
def test_classify(activity_type, name, expected):
    assert activity.classify(activity_type, name) == expected


def test_air_sports_are_3d():
    assert activity.prefers_3d(activity.AIR)
    assert not activity.prefers_3d(activity.GROUND)


def test_presets_fit_the_watch():
    for name, activity_id, gps, recording in activity.AIR_SPORT_PRESETS:
        assert len(name) <= activity.WATCH_NAME_LENGTH
        assert activity_id in activity.ACTIVITY_NAMES
        assert gps >= 1 and recording >= 1


def test_make_mode():
    mode = activity.make_mode("A very long mode name", 92, 7, 1, 1, 1)
    assert mode["Name"] == "A very long mod"
    assert (mode["ActivityID"], mode["CustomModeID"], mode["AltiBaroMode"]) == (92, 7, 1)


def test_activity_names():
    assert activity.activity_name(92) == "Paragliding"
    assert activity.activity_name(10) == "Yoga / pilates"
    assert activity.activity_name(999) == "Activity 999"
