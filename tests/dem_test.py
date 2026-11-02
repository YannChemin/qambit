"""Tests of qambit.core.dem (no network)."""

import pytest

from qambit.core import dem


def test_tile_names():
    assert dem.copernicus_tile_name(45, 6) == "Copernicus_DSM_COG_30_N45_00_E006_00_DEM"
    assert dem.copernicus_tile_name(-1, -3, "glo30") == "Copernicus_DSM_COG_10_S01_00_W003_00_DEM"
    url = dem.copernicus_tile_url(45, 6, "glo30")
    assert url.startswith("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N45")


def test_tiles_for_box():
    assert dem.tiles_for_box(6.8, 45.8, 7.1, 46.0) == [(45, 6), (45, 7)]
    # A box ending on a whole degree does not take the next cell.
    assert dem.tiles_for_box(6.0, 45.0, 7.0, 46.0) == [(45, 6)]
    with pytest.raises(ValueError):
        dem.tiles_for_box(0, 0, 10, 10)
    with pytest.raises(ValueError):
        dem.tiles_for_box(1, 1, 1, 2)


def test_pick_source():
    assert dem.pick_source(6.8, 45.8, 7.1, 46.0) == "glo30"
    assert dem.pick_source(5, 44, 7, 46) == "glo90"


def test_terrarium_uri():
    uri = dem.terrarium_uri()
    assert "interpretation=terrariumterrain" in uri
    assert "%7Bz%7D" in uri
