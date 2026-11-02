"""
MODULE:    qambit.core.dem
AUTHOR(S): Yann Chemin
PURPOSE:   Elevation sources for the 3D view and the elevation profile: the
           global Terrain Tiles (Mapzen "terrarium" encoding on AWS Open Data)
           and the Copernicus GLO-30/GLO-90 DEM, cut around the logs.
SPDX-License-Identifier: Unlicense

Neither source needs an account or a key. The Copernicus tiles are read the
way the r.in.dem GRASS addon reads them: a GDAL VRT over /vsicurl/, warped
to the requested box so that GDAL only fetches the overview it needs.
"""

import hashlib
import math
import os
import urllib.error
import urllib.request

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TERRARIUM_MAX_ZOOM = 15

COPERNICUS = {
    # Resolution name: (bucket, tile resolution code, pixel size in degrees)
    "glo30": ("copernicus-dem-30m", "10", 1.0 / 3600),
    "glo90": ("copernicus-dem-90m", "30", 1.0 / 1200),
}
MAX_TILES = 25


def terrarium_uri():
    """QGIS raster ("wms" provider) URI of the Terrain Tiles as an elevation layer."""
    url = TERRARIUM_URL.replace("{", "%7B").replace("}", "%7D")
    return "type=xyz&url={}&zmin=0&zmax={}&interpretation=terrariumterrain".format(
        url, TERRARIUM_MAX_ZOOM
    )


def copernicus_tile_name(lat, lon, source="glo90"):
    """
    Name of the tile whose south-west corner is (lat, lon), e.g.
    "Copernicus_DSM_COG_30_N47_00_W003_00_DEM".
    """
    code = COPERNICUS[source][1]
    return "Copernicus_DSM_COG_{}_{}{:02d}_00_{}{:03d}_00_DEM".format(
        code, "S" if lat < 0 else "N", abs(lat), "W" if lon < 0 else "E", abs(lon)
    )


def copernicus_tile_url(lat, lon, source="glo90"):
    name = copernicus_tile_name(lat, lon, source)
    return "https://{}.s3.amazonaws.com/{}/{}.tif".format(COPERNICUS[source][0], name, name)


def tiles_for_box(west, south, east, north):
    """
    The 1-degree cells (lat, lon of the south-west corner) covering a box.

    :raises ValueError: On an empty box or one needing more than MAX_TILES tiles
    """
    west, east = max(-180.0, west), min(180.0, east)
    south, north = max(-90.0, south), min(90.0, north)
    if not (east > west and north > south):
        raise ValueError("Empty area for the elevation model.")
    lats = range(math.floor(south), math.floor(north - 1e-9) + 1)
    lons = range(math.floor(west), math.floor(east - 1e-9) + 1)
    if len(lats) * len(lons) > MAX_TILES:
        raise ValueError(
            "Area too large for the elevation model ({} tiles of 1 degree, at most {}).".format(
                len(lats) * len(lons), MAX_TILES
            )
        )
    return [(lat, lon) for lat in lats for lon in lons]


def pick_source(west, south, east, north):
    """GLO-30 for areas up to about 1 degree across, GLO-90 above."""
    return "glo30" if max(east - west, north - south) <= 1.0 else "glo90"


def _tile_exists(url, timeout=20):
    """Ocean tiles do not exist in the buckets (HTTP 404)."""
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return False
        raise


def build_copernicus_dem(west, south, east, north, cache_dir, source=None, feedback=None):
    """
    Writes a GeoTIFF of the Copernicus DEM over a box (WGS84 degrees), at the
    native resolution, and returns its path. The result is cached by box.

    :param feedback: Optional callable(done, total, message) for progress
    :raises ValueError: When the box is too large or entirely sea
    :raises OSError: When the tiles cannot be reached
    """
    from osgeo import gdal

    source = source or pick_source(west, south, east, north)
    key = "{}_{:.4f}_{:.4f}_{:.4f}_{:.4f}".format(source, west, south, east, north)
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(
        cache_dir,
        "copernicus_{}.tif".format(hashlib.sha1(key.encode()).hexdigest()[:16]),
    )
    if os.path.exists(out):
        return out

    cells = tiles_for_box(west, south, east, north)
    sources = []
    for i, (lat, lon) in enumerate(cells):
        if feedback:
            feedback(i, len(cells) + 1, copernicus_tile_name(lat, lon, source))
        url = copernicus_tile_url(lat, lon, source)
        try:
            if _tile_exists(url):
                sources.append("/vsicurl/" + url)
        except (urllib.error.URLError, OSError) as e:
            raise OSError("The Copernicus DEM cannot be reached: {}".format(e)) from e
    if not sources:
        raise ValueError("No Copernicus DEM tile over this area (open sea).")

    gdal.UseExceptions()
    vrt = out[:-4] + ".vrt"
    gdal.BuildVRT(vrt, sources)
    if feedback:
        feedback(len(cells), len(cells) + 1, "warp")
    pixel = COPERNICUS[source][2]
    gdal.Warp(
        out + ".part",
        vrt,
        format="GTiff",
        outputBounds=(west, south, east, north),
        xRes=pixel,
        yRes=pixel,
        dstSRS="EPSG:4326",
        resampleAlg="bilinear",
        # Sea tiles are missing; sea level is the right value there
        dstNodata=None,
        creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"],
    )
    os.replace(out + ".part", out)
    return out
