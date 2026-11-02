"""Tests of qambit.core.logparser."""

import datetime

import pytest

from qambit.core.logparser import find_logs, read_log


def test_flight_header(flight_log):
    log = read_log(flight_log)
    assert log.log_id == "log_TEST000000000001_2026_07_01_10_00_00"
    assert log.activity == "Paragliding"
    assert log.activity_type == 92
    assert log.serial == "TEST000000000001"
    assert log.duration_s == 45.0
    assert log.distance_m == 1200.0
    assert (log.alt_min_m, log.alt_max_m) == (1035, 1435)
    assert (log.hr_avg, log.hr_max) == (122, 124)
    assert log.category == "air"
    assert log.prefers_3d


def test_flight_points(flight_log):
    log = read_log(flight_log)
    # The 0,0 fix and the "position" repeat of the last fix are dropped.
    assert len(log.points) == 5
    first, last = log.points[0], log.points[-1]
    assert (first.lat, first.lon) == pytest.approx((45.92, 6.87))
    # The pressure altitude wins over the GPS one.
    assert first.alt_m == 1035.0
    assert last.alt_m == 1435.0
    assert last.speed_kmh == pytest.approx(1004 * 0.036)
    assert last.vertical_speed_ms == 1.5
    assert last.temperature_c == 21.5
    assert last.ehpe_m == 4.5
    assert last.satellites == 9
    assert last.utc == datetime.datetime(2026, 7, 1, 8, 0, 43, tzinfo=datetime.timezone.utc)
    assert [p.elapsed_s for p in log.points] == [3.0, 13.0, 23.0, 33.0, 43.0]


def test_laps(flight_log):
    (lap,) = read_log(flight_log).laps
    assert lap.kind == "Start"
    assert lap.duration_s == 0.6


def test_header_only(flight_log):
    log = read_log(flight_log, header_only=True)
    assert log.activity == "Paragliding"
    assert log.points == []


def test_not_a_log(tmp_path):
    path = tmp_path / "log_x.log"
    path.write_text("<?xml version='1.0'?><other/>")
    with pytest.raises(ValueError):
        read_log(str(path))


def test_find_logs(tmp_path):
    for name in ("log_b.log", "log_a.log", "other.log", "log_c.txt"):
        (tmp_path / name).write_text("")
    (tmp_path / "movescount").mkdir()
    assert [p.rsplit("/", 1)[1] for p in find_logs(str(tmp_path))] == ["log_a.log", "log_b.log"]
    assert find_logs(str(tmp_path / "missing")) == []
