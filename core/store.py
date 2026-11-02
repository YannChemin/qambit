"""
MODULE:    qambit.core.store
AUTHOR(S): Yann Chemin
PURPOSE:   Keeps the openambit logs in one GeoPackage, the layers QGIS shows:
           tracks (LineStringZM: Z altitude, M seconds from the start), the
           position fixes with their sensor values, and the laps.
SPDX-License-Identifier: Unlicense

Imports are incremental: a log whose file has not changed since its last
import is skipped, and a changed one replaces its previous features.
"""

import datetime
import os

from osgeo import ogr, osr

from .logparser import read_log

TRACKS = "ambit_tracks"
POINTS = "ambit_points"
LAPS = "ambit_laps"

_TRACK_FIELDS = [
    ("log_id", ogr.OFTString),
    ("start", ogr.OFTDateTime),
    ("activity", ogr.OFTString),
    ("activity_type", ogr.OFTInteger),
    ("activity_type_name", ogr.OFTString),
    ("category", ogr.OFTString),
    ("prefers_3d", ogr.OFTInteger),
    ("device", ogr.OFTString),
    ("serial", ogr.OFTString),
    ("duration_s", ogr.OFTReal),
    ("distance_km", ogr.OFTReal),
    ("ascent_m", ogr.OFTReal),
    ("descent_m", ogr.OFTReal),
    ("alt_min_m", ogr.OFTReal),
    ("alt_max_m", ogr.OFTReal),
    ("energy_kcal", ogr.OFTReal),
    ("hr_avg", ogr.OFTInteger),
    ("hr_max", ogr.OFTInteger),
    ("n_points", ogr.OFTInteger),
    ("source_file", ogr.OFTString),
    ("source_mtime", ogr.OFTReal),
    ("source_size", ogr.OFTInteger64),
]
_POINT_FIELDS = [
    ("log_id", ogr.OFTString),
    ("utc", ogr.OFTDateTime),
    ("elapsed_s", ogr.OFTReal),
    ("alt_m", ogr.OFTReal),
    ("hr_bpm", ogr.OFTInteger),
    ("speed_kmh", ogr.OFTReal),
    ("cadence_rpm", ogr.OFTInteger),
    ("distance_m", ogr.OFTReal),
    ("vspeed_ms", ogr.OFTReal),
    ("temperature_c", ogr.OFTReal),
    ("ehpe_m", ogr.OFTReal),
    ("satellites", ogr.OFTInteger),
    ("category", ogr.OFTString),
]
_LAP_FIELDS = [
    ("log_id", ogr.OFTString),
    ("kind", ogr.OFTString),
    ("utc", ogr.OFTDateTime),
    ("elapsed_s", ogr.OFTReal),
    ("duration_s", ogr.OFTReal),
    ("distance_m", ogr.OFTReal),
]
_LAYERS = {
    TRACKS: (ogr.wkbLineStringZM, _TRACK_FIELDS),
    POINTS: (ogr.wkbPoint25D, _POINT_FIELDS),
    LAPS: (ogr.wkbPoint25D, _LAP_FIELDS),
}


def _open(path):
    ogr.UseExceptions()
    driver = ogr.GetDriverByName("GPKG")
    ds = driver.Open(path, 1) if os.path.exists(path) else driver.CreateDataSource(path)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    for name, (geom_type, fields) in _LAYERS.items():
        if ds.GetLayerByName(name) is None:
            layer = ds.CreateLayer(name, srs, geom_type, ["SPATIAL_INDEX=YES"])
            for field_name, field_type in fields:
                layer.CreateField(ogr.FieldDefn(field_name, field_type))
    return ds


def _set_datetime(feature, name, value):
    if value is None:
        return
    if value.tzinfo is not None:
        # 100 is OGR's flag for UTC
        value = value.astimezone(datetime.timezone.utc)
        feature.SetField(name, value.year, value.month, value.day, value.hour,
                         value.minute, value.second + value.microsecond / 1e6, 100)  # fmt: skip
    else:
        feature.SetField(name, value.year, value.month, value.day, value.hour,
                         value.minute, float(value.second), 0)  # fmt: skip


def _set(feature, name, value):
    if value is not None:
        feature.SetField(name, value)


def imported_state(path):
    """
    The logs already in the store.

    :return: dict log_id -> (source_mtime, source_size)
    """
    if not os.path.exists(path):
        return {}
    ogr.UseExceptions()
    ds = ogr.Open(path)
    layer = ds.GetLayerByName(TRACKS)
    if layer is None:
        return {}
    return {
        f.GetField("log_id"): (f.GetField("source_mtime"), f.GetField("source_size")) for f in layer
    }


def _delete_log(ds, log_id):
    quoted = log_id.replace("'", "''")
    for name in _LAYERS:
        ds.ExecuteSQL("DELETE FROM \"{}\" WHERE log_id = '{}'".format(name, quoted))


def _write_log(ds, log, stat):
    tracks, points, laps = (ds.GetLayerByName(n) for n in (TRACKS, POINTS, LAPS))
    category = log.category

    line = ogr.Geometry(ogr.wkbLineStringZM)
    for p in log.points:
        line.AddPointZM(p.lon, p.lat, p.alt_m if p.alt_m is not None else 0.0, p.elapsed_s)
    track = ogr.Feature(tracks.GetLayerDefn())
    track.SetGeometry(line)
    track.SetField("log_id", log.log_id)
    _set_datetime(track, "start", log.start)
    _set(track, "activity", log.activity)
    _set(track, "activity_type", log.activity_type)
    _set(track, "activity_type_name", log.activity_type_name)
    _set(track, "category", category)
    _set(track, "prefers_3d", 1 if log.prefers_3d else 0)
    _set(track, "device", log.device_name)
    _set(track, "serial", log.serial)
    _set(track, "duration_s", log.duration_s)
    _set(track, "distance_km", log.distance_m / 1000.0)
    _set(track, "ascent_m", log.ascent_m)
    _set(track, "descent_m", log.descent_m)
    _set(track, "alt_min_m", log.alt_min_m)
    _set(track, "alt_max_m", log.alt_max_m)
    _set(track, "energy_kcal", log.energy_kcal)
    _set(track, "hr_avg", log.hr_avg)
    _set(track, "hr_max", log.hr_max)
    _set(track, "n_points", len(log.points))
    _set(track, "source_file", log.path)
    _set(track, "source_mtime", stat[0])
    _set(track, "source_size", stat[1])
    tracks.CreateFeature(track)

    defn = points.GetLayerDefn()
    for p in log.points:
        f = ogr.Feature(defn)
        g = ogr.Geometry(ogr.wkbPoint25D)
        g.AddPoint(p.lon, p.lat, p.alt_m if p.alt_m is not None else 0.0)
        f.SetGeometry(g)
        f.SetField("log_id", log.log_id)
        _set_datetime(f, "utc", p.utc)
        _set(f, "elapsed_s", p.elapsed_s)
        _set(f, "alt_m", p.alt_m)
        _set(f, "hr_bpm", p.hr_bpm)
        _set(f, "speed_kmh", p.speed_kmh)
        _set(f, "cadence_rpm", p.cadence_rpm)
        _set(f, "distance_m", p.distance_m)
        _set(f, "vspeed_ms", p.vertical_speed_ms)
        _set(f, "temperature_c", p.temperature_c)
        _set(f, "ehpe_m", p.ehpe_m)
        _set(f, "satellites", p.satellites)
        _set(f, "category", category)
        points.CreateFeature(f)

    # A lap is placed at the last fix logged before it
    defn = laps.GetLayerDefn()
    for lap in log.laps:
        before = [p for p in log.points if p.elapsed_s <= lap.elapsed_s]
        where = before[-1] if before else log.points[0]
        f = ogr.Feature(defn)
        g = ogr.Geometry(ogr.wkbPoint25D)
        g.AddPoint(where.lon, where.lat, where.alt_m if where.alt_m is not None else 0.0)
        f.SetGeometry(g)
        f.SetField("log_id", log.log_id)
        _set(f, "kind", lap.kind)
        _set_datetime(f, "utc", lap.utc)
        _set(f, "elapsed_s", lap.elapsed_s)
        _set(f, "duration_s", lap.duration_s)
        _set(f, "distance_m", lap.distance_m)
        laps.CreateFeature(f)


def import_logs(paths, gpkg, progress=None, is_canceled=None, force=False):
    """
    Imports openambit log files into the GeoPackage.

    :param paths: Log files (see logparser.find_logs)
    :param gpkg: GeoPackage path, created when missing
    :param progress: Optional callable(done, total, log_id)
    :param is_canceled: Optional callable returning True to stop
    :param force: Re-import logs whose file has not changed
    :return: dict with "imported", "unchanged" and "skipped" (log_id, reason) lists
    """
    result = {"imported": [], "unchanged": [], "skipped": []}
    known = imported_state(gpkg)
    ds = _open(gpkg)
    try:
        for i, path in enumerate(paths):
            if is_canceled and is_canceled():
                break
            st = os.stat(path)
            stat = (st.st_mtime, st.st_size)
            log_id = os.path.splitext(os.path.basename(path))[0]
            if progress:
                progress(i, len(paths), log_id)
            previous = known.get(log_id)
            if (
                not force
                and previous
                and abs((previous[0] or 0) - stat[0]) < 1e-3
                and previous[1] == stat[1]
            ):
                result["unchanged"].append(log_id)
                continue
            try:
                log = read_log(path)
            except ValueError as e:
                result["skipped"].append((log_id, str(e)))
                continue
            if len(log.points) < 2:
                result["skipped"].append((log_id, "fewer than two GPS fixes"))
                continue
            ds.StartTransaction()
            try:
                _delete_log(ds, log.log_id)
                _write_log(ds, log, stat)
                ds.CommitTransaction()
            except Exception:
                ds.RollbackTransaction()
                raise
            result["imported"].append(log.log_id)
        if progress:
            progress(len(paths), len(paths), "")
    finally:
        ds = None
    return result


def _where(log_ids):
    quoted = ",".join("'{}'".format(i.replace("'", "''")) for i in log_ids)
    return "log_id IN ({})".format(quoted)


def list_tracks(path):
    """
    The moves of the store, for the panel list.

    :return: List of dicts (log_id, start "YYYY-MM-DD HH:MM", activity,
        category, distance_km, duration_s, ascent_m, prefers_3d)
    """
    if not os.path.exists(path):
        return []
    ogr.UseExceptions()
    ds = ogr.Open(path)
    layer = ds.GetLayerByName(TRACKS)
    if layer is None:
        return []
    rows = []
    for f in layer:
        y, mo, d, h, mi = (
            f.GetFieldAsDateTime("start")[:5] if f.IsFieldSetAndNotNull("start") else (0,) * 5
        )
        rows.append(
            {
                "log_id": f.GetField("log_id"),
                "start": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}".format(y, mo, d, h, mi) if y else "",
                "activity": f.GetField("activity"),
                "category": f.GetField("category"),
                "distance_km": f.GetField("distance_km"),
                "duration_s": f.GetField("duration_s"),
                "ascent_m": f.GetField("ascent_m"),
                "prefers_3d": bool(f.GetField("prefers_3d")),
            }
        )
    return rows


def tracks_box(path, log_ids=None):
    """
    WGS84 box (west, south, east, north) of some moves, or of all.

    :return: The box, or None when no move matches
    """
    if not os.path.exists(path):
        return None
    ogr.UseExceptions()
    ds = ogr.Open(path)
    layer = ds.GetLayerByName(TRACKS)
    if layer is None:
        return None
    if log_ids:
        layer.SetAttributeFilter(_where(log_ids))
    if layer.GetFeatureCount() == 0:
        return None
    west, east, south, north = layer.GetExtent()
    return west, south, east, north
