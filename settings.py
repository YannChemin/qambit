"""
MODULE:    qambit.settings
AUTHOR(S): Yann Chemin
PURPOSE:   The plugin options, kept in the QGIS settings (QgsSettings).
SPDX-License-Identifier: Unlicense
"""

import os

from qgis.core import QgsSettings

_PREFIX = "qambit/"

DEFAULTS = {
    # openambit-cli of openambit2; empty means "find it"
    "cli_path": "",
    # Where openambit2 keeps logs, sport modes and training plans
    "data_dir": os.path.expanduser("~/.openambit"),
    "gpkg": os.path.expanduser("~/.openambit/qambit.gpkg"),
    "orbit_script": os.path.expanduser("~/dev/openambit2/tools/rinex2ubx_ambit.py"),
    "orbit_file": os.path.expanduser("~/.openambit/orbit_cache.uo"),
    "dem_cache": os.path.expanduser("~/.cache/qambit/dem"),
    # "auto" uses IGN LiDAR HD where it covers the area (France), else the
    # Copernicus DEM; "lidarhd" and "copernicus" force one.
    "dem_source": "auto",
    # LiDAR HD model: "mns" (surface, 50 cm DSM) or "mnt" (bare earth)
    "lidarhd_product": "mns",
    "read_logs": True,
    "sync_time": True,
    "sync_orbit": True,
    "sync_on_connect": False,
    "air_sports_3d": True,
    # HCMGIS basemap names
    "basemap_2d": "Esri Topographic",
    "basemap_3d": "Esri Imagery",
}


def value(key):
    default = DEFAULTS[key]
    v = QgsSettings().value(_PREFIX + key, default)
    if isinstance(default, bool):
        return v if isinstance(v, bool) else str(v).lower() in ("true", "1")
    return v if v is not None else default


def set_value(key, v):
    QgsSettings().setValue(_PREFIX + key, v)


def sport_modes_path():
    return os.path.join(value("data_dir"), "sport_modes.json")


def training_plans_path():
    return os.path.join(value("data_dir"), "training_plans.json")
