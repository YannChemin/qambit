"""Tests of qambit.core.store."""

import os
import shutil

import pytest
from osgeo import ogr

from qambit.core import store


@pytest.fixture
def logs(tmp_path, flight_log):
    folder = tmp_path / "openambit"
    folder.mkdir()
    shutil.copy(flight_log, folder)
    # A move without GPS: imported as skipped.
    empty = folder / "log_TEST000000000001_2026_07_02_10_00_00.log"
    text = open(flight_log).read()
    start, end = text.index("<Samples>"), text.index("</Samples>")
    empty.write_text(text[:start] + "<Samples>\n" + text[end:])
    return sorted(str(p) for p in folder.iterdir())


def test_import(tmp_path, logs):
    gpkg = str(tmp_path / "store.gpkg")
    seen = []
    result = store.import_logs(logs, gpkg, lambda d, t, i: seen.append((d, t)))
    assert len(result["imported"]) == 1
    assert result["skipped"][0][1] == "fewer than two GPS fixes"
    assert seen[-1] == (2, 2)

    ds = ogr.Open(gpkg)
    tracks = ds.GetLayerByName(store.TRACKS)
    assert tracks.GetGeomType() == ogr.wkbLineStringZM
    track = tracks.GetNextFeature()
    assert track.GetField("category") == "air"
    assert track.GetField("prefers_3d") == 1
    line = track.GetGeometryRef()
    assert line.GetPointCount() == 5
    assert line.GetZ(4) == 1435.0
    assert line.GetM(4) == 43.0
    assert ds.GetLayerByName(store.POINTS).GetFeatureCount() == 5
    assert ds.GetLayerByName(store.LAPS).GetFeatureCount() == 1
    point = ds.GetLayerByName(store.POINTS).GetNextFeature()
    assert point.GetField("hr_bpm") == 120
    assert point.GetFieldAsString("utc").startswith("2026/07/01 08:00:03")


def test_incremental(tmp_path, logs):
    gpkg = str(tmp_path / "store.gpkg")
    store.import_logs(logs, gpkg)
    again = store.import_logs(logs, gpkg)
    assert again["imported"] == []
    assert len(again["unchanged"]) == 1
    # A changed file replaces its features instead of adding to them.
    os.utime(logs[0], (1, 1))
    third = store.import_logs(logs, gpkg)
    assert len(third["imported"]) == 1
    assert ogr.Open(gpkg).GetLayerByName(store.POINTS).GetFeatureCount() == 5
    forced = store.import_logs(logs, gpkg, force=True)
    assert len(forced["imported"]) == 1


def test_list_and_box(tmp_path, logs):
    gpkg = str(tmp_path / "store.gpkg")
    assert store.list_tracks(gpkg) == []
    assert store.tracks_box(gpkg) is None
    store.import_logs(logs, gpkg)
    (row,) = store.list_tracks(gpkg)
    assert row["start"] == "2026-07-01 10:00"
    assert row["activity"] == "Paragliding"
    assert row["prefers_3d"]
    assert row["distance_km"] == pytest.approx(1.2)
    box = store.tracks_box(gpkg, [row["log_id"]])
    assert box == pytest.approx((6.87, 45.92, 6.878, 45.924))
    assert store.tracks_box(gpkg, ["nothing"]) is None


def test_cancel(tmp_path, logs):
    result = store.import_logs(logs, str(tmp_path / "s.gpkg"), is_canceled=lambda: True)
    assert result["imported"] == [] and result["unchanged"] == []
