"""Tests of qambit.core.lidarhd; set QAMBIT_NETWORK=1 to also query IGN."""

import os

import pytest

from qambit.core import lidarhd

CHAMONIX = (6.865, 45.900, 6.871, 45.906)
network = pytest.mark.skipif(not os.environ.get("QAMBIT_NETWORK"), reason="QAMBIT_NETWORK not set")


def test_lambert93_box():
    xmin, ymin, xmax, ymax = lidarhd.box_to_lambert93(*CHAMONIX)
    # Chamonix is near x = 999 km, y = 6540 km in Lambert-93.
    assert 998_000 < xmin < xmax < 1_001_000
    assert 6_539_000 < ymin < ymax < 6_542_000


def test_in_metropole():
    assert lidarhd.in_metropole(*CHAMONIX)
    assert not lidarhd.in_metropole(-61.6, 16.0, -61.5, 16.1)


def test_pick_resolution():
    assert lidarhd.pick_resolution((0, 0, 2000, 2000)) == 0.5
    assert lidarhd.pick_resolution((0, 0, 20_000, 20_000)) == 5.0
    with pytest.raises(ValueError):
        lidarhd.pick_resolution((0, 0, 1_000_000, 1_000_000))


def test_snap_and_chunks():
    box = lidarhd.snap((10.2, 20.7, 1510.1, 1020.3), 0.5)
    assert box == (10.0, 20.5, 1510.5, 1020.5)
    pieces = lidarhd.chunks(box, 0.5, size=2000)
    # 3001 x 2000 pixels: two columns of chunks, one row.
    assert [(w, h) for *_, w, h in pieces] == [(2000, 2000), (1001, 2000)]
    assert pieces[0][:4] == (10.0, 20.5, 1010.0, 1020.5)
    assert pieces[1][2] == 1510.5


def test_getmap_url():
    url = lidarhd.getmap_url("mnt", (1.0, 2.0, 3.0, 4.0, 4, 4))
    assert "LAYERS=IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93" in url
    assert "BBOX=1.0,2.0,3.0,4.0" in url
    assert "CRS=EPSG:2154" in url


def test_outside_france(tmp_path):
    with pytest.raises(lidarhd.NotCovered):
        lidarhd.build_lidarhd_dem(-61.6, 16.0, -61.5, 16.1, str(tmp_path))


@network
def test_build_small_dsm(tmp_path):
    from osgeo import gdal

    path = lidarhd.build_lidarhd_dem(*CHAMONIX, str(tmp_path))
    ds = gdal.Open(path)
    assert ds.GetGeoTransform()[1] == 0.5
    low, high = ds.GetRasterBand(1).ComputeRasterMinMax(False)
    assert 1000 < low < high < 2500
    # The second call comes from the cache.
    assert lidarhd.build_lidarhd_dem(*CHAMONIX, str(tmp_path)) == path
