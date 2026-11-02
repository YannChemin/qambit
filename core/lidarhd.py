"""
MODULE:    qambit.core.lidarhd
AUTHOR(S): Yann Chemin
PURPOSE:   Fetches IGN LiDAR HD elevation (metropolitan France, 50 cm surface
           or terrain model) around a box, as one GeoTIFF for the 3D terrain
           and the elevation profile.
SPDX-License-Identifier: Unlicense

Same data and services as the r.in.lidarhd GRASS addon: the Geoplateforme WFS
lists the 1 km tiles (and so the coverage), and the WMS-R layers behind each
tile URL serve the elevation as Float32 GeoTIFF for any Lambert-93 box and
size. So the box is fetched straight at the resolution the view needs,
in chunks of at most CHUNK_PIXELS a side, instead of downloading 16 MB per
square kilometre at 50 cm.
"""

import hashlib
import json
import math
import os
import urllib.parse
import urllib.request

WFS_URL = "https://data.geopf.fr/wfs/ows"
WFS_LAYER = "IGNF_LIDAR-HD_METADONNEE:metadata"
WMS_URL = "https://data.geopf.fr/wms-r"
LAYERS = {
    "mns": "IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
    "mnt": "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
}
NODATA = -9999.0
NATIVE_RESOLUTION = 0.5
# Resolutions tried from the finest, in metres.
RESOLUTIONS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 25.0)
# At most this many pixels in the output (64 Mpx, 256 MB of Float32, a few
# minutes of download at the service's ~4 MB/s).
MAX_PIXELS = 64_000_000
CHUNK_PIXELS = 2000
# The approximate extent of metropolitan France (WGS84), checked before any
# request.
METROPOLE_BOX = (-5.5, 41.2, 10.0, 51.3)
# Share of the 1 km tiles of the box that must exist to call it covered.
MIN_COVERAGE = 0.9


class NotCovered(ValueError):
    """The box is outside the LiDAR HD coverage."""


def _osr():
    from osgeo import osr

    osr.UseExceptions()
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    l93 = osr.SpatialReference()
    l93.ImportFromEPSG(2154)
    l93.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(wgs84, l93)


def box_to_lambert93(west, south, east, north):
    """The Lambert-93 box (xmin, ymin, xmax, ymax) holding a WGS84 box."""
    transform = _osr()
    xs, ys = [], []
    # Edges are sampled, since a lon/lat box is curved in Lambert-93.
    for i in range(11):
        t = i / 10.0
        for lon, lat in (
            (west + t * (east - west), south),
            (west + t * (east - west), north),
            (west, south + t * (north - south)),
            (east, south + t * (north - south)),
        ):
            x, y, _ = transform.TransformPoint(lon, lat)
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def in_metropole(west, south, east, north):
    mw, ms, me, mn = METROPOLE_BOX
    return west >= mw and east <= me and south >= ms and north <= mn


def pick_resolution(box_l93, max_pixels=MAX_PIXELS):
    """The finest resolution keeping the box under max_pixels."""
    width = box_l93[2] - box_l93[0]
    height = box_l93[3] - box_l93[1]
    for resolution in RESOLUTIONS:
        if (width / resolution) * (height / resolution) <= max_pixels:
            return resolution
    raise ValueError(
        "The box is too large for LiDAR HD ({:.0f} x {:.0f} km); use the Copernicus DEM.".format(
            width / 1000, height / 1000
        )
    )


def snap(box_l93, resolution):
    """Aligns a box on the resolution grid, outwards."""
    xmin, ymin, xmax, ymax = box_l93
    return (
        math.floor(xmin / resolution) * resolution,
        math.floor(ymin / resolution) * resolution,
        math.ceil(xmax / resolution) * resolution,
        math.ceil(ymax / resolution) * resolution,
    )


def chunks(box_l93, resolution, size=CHUNK_PIXELS):
    """
    Splits a snapped box into GetMap requests.

    :return: List of (xmin, ymin, xmax, ymax, width, height)
    """
    xmin, ymin, xmax, ymax = box_l93
    columns = int(round((xmax - xmin) / resolution))
    rows = int(round((ymax - ymin) / resolution))
    out = []
    for row in range(0, rows, size):
        h = min(size, rows - row)
        top = ymax - row * resolution
        for col in range(0, columns, size):
            w = min(size, columns - col)
            left = xmin + col * resolution
            out.append((left, top - h * resolution, left + w * resolution, top, w, h))
    return out


def getmap_url(product, chunk):
    xmin, ymin, xmax, ymax, width, height = chunk
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "EXCEPTIONS": "text/xml",
        "REQUEST": "GetMap",
        "LAYERS": LAYERS[product],
        "FORMAT": "image/geotiff",
        "STYLES": "",
        "CRS": "EPSG:2154",
        "BBOX": "{},{},{},{}".format(xmin, ymin, xmax, ymax),
        "WIDTH": width,
        "HEIGHT": height,
    }
    return WMS_URL + "?" + urllib.parse.urlencode(params, safe=":,")


def tile_count(box_l93, timeout=60):
    """Number of LiDAR HD tiles the WFS lists over a Lambert-93 box."""
    xmin, ymin, xmax, ymax = box_l93
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAME": WFS_LAYER,
        "RESULTTYPE": "hits",
        "SRSNAME": "EPSG:2154",
        "BBOX": "{},{},{},{},urn:ogc:def:crs:EPSG::2154".format(xmin, ymin, xmax, ymax),
    }
    url = WFS_URL + "?" + urllib.parse.urlencode(params, safe=":,")
    with urllib.request.urlopen(url, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
    # <wfs:FeatureCollection numberMatched="N" ...>
    marker = 'numberMatched="'
    start = text.find(marker)
    if start < 0:
        raise RuntimeError("Unexpected LiDAR HD WFS answer: " + text[:200])
    value = text[start + len(marker) : text.index('"', start + len(marker))]
    return int(value)


def coverage(box_l93):
    """Share (0-1) of the 1 km tiles of a box that LiDAR HD has."""
    xmin, ymin, xmax, ymax = box_l93
    expected = (math.ceil(xmax / 1000) - math.floor(xmin / 1000)) * (
        math.ceil(ymax / 1000) - math.floor(ymin / 1000)
    )
    return min(1.0, tile_count(box_l93) / max(expected, 1))


def _download(url, path, timeout=300):
    tmp = path + ".part"
    try:
        with (
            urllib.request.urlopen(url, timeout=timeout) as response,
            open(tmp, "wb") as out,
        ):
            kind = response.headers.get("Content-Type", "")
            if "xml" in kind:
                raise RuntimeError(
                    "LiDAR HD service error: " + response.read(500).decode("utf-8", "replace")
                )
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                out.write(block)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def build_lidarhd_dem(
    west,
    south,
    east,
    north,
    cache_dir,
    product="mns",
    resolution=None,
    feedback=None,
    is_canceled=None,
):
    """
    Writes LiDAR HD elevation around a WGS84 box to a cached GeoTIFF (EPSG:2154).

    :param product: "mns" (surface model, first return) or "mnt" (bare earth)
    :param resolution: Metres, or None for the finest that fits MAX_PIXELS
    :param feedback: Optional callable(done, total, what)
    :param is_canceled: Optional callable returning True to stop
    :raises NotCovered: When the box is outside the LiDAR HD coverage
    :return: Path of the GeoTIFF
    """
    from osgeo import gdal

    gdal.UseExceptions()
    if product not in LAYERS:
        raise ValueError("Unknown LiDAR HD product {!r} (mns or mnt).".format(product))
    if not in_metropole(west, south, east, north):
        raise NotCovered("LiDAR HD covers metropolitan France only.")
    box = box_to_lambert93(west, south, east, north)
    share = coverage(box)
    if share < MIN_COVERAGE:
        raise NotCovered(
            "LiDAR HD covers only {:.0%} of this area; use the Copernicus DEM.".format(share)
        )
    resolution = resolution or pick_resolution(box)
    box = snap(box, resolution)

    key = hashlib.sha1(json.dumps([product, resolution, box]).encode()).hexdigest()[:16]
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, "lidarhd_{}_{:g}m_{}.tif".format(product, resolution, key))
    if os.path.exists(out):
        return out

    parts_dir = out[:-4] + "_parts"
    os.makedirs(parts_dir, exist_ok=True)
    pieces = chunks(box, resolution)
    paths = []
    for i, chunk in enumerate(pieces):
        if is_canceled and is_canceled():
            raise RuntimeError("Canceled.")
        if feedback:
            feedback(i, len(pieces), "LiDAR HD chunk {}/{}".format(i + 1, len(pieces)))
        path = os.path.join(parts_dir, "{:04d}.tif".format(i))
        if not os.path.exists(path):
            _download(getmap_url(product, chunk), path)
        paths.append(path)

    vrt = gdal.BuildVRT(out[:-4] + ".vrt", paths, srcNodata=NODATA, VRTNodata=NODATA)
    gdal.Translate(
        out + ".part",
        vrt,
        format="GTiff",
        creationOptions=[
            "COMPRESS=DEFLATE",
            "PREDICTOR=3",
            "TILED=YES",
            "BIGTIFF=IF_SAFER",
        ],
    )
    vrt = None
    os.replace(out + ".part", out)
    os.unlink(out[:-4] + ".vrt")
    for path in paths:
        os.unlink(path)
    os.rmdir(parts_dir)
    if feedback:
        feedback(len(pieces), len(pieces), "")
    return out
