"""
MODULE:    qambit.qgis_layers
AUTHOR(S): Yann Chemin
PURPOSE:   Shows the openambit store in QGIS: track, point and lap layers
           styled by activity, time-enabled, elevation-enabled and 3D-ready;
           basemaps from HCMGIS; terrain for the 3D views and the elevation
           profile.
SPDX-License-Identifier: Unlicense
"""

import os

from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsDateTimeRange,
    QgsLayerTreeGroup,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterDemTerrainProvider,
    QgsRasterLayer,
    QgsRendererCategory,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor

from .core import dem, store

GROUP_NAME = "Ambit"
TERRAIN_NAME = "Terrain Tiles (elevation)"

# Category colours, shared by the 2D, 3D and profile views
CATEGORY_COLORS = {
    "air": "#e01b24",
    "ground": "#3584e4",
    "water": "#1a9e8f",
    "vertical": "#c64600",
    "underwater": "#813d9c",
}


def translate(context, text):
    return QCoreApplication.translate(context, text)


def category_label(key):
    return {
        "air": translate("QAmbit", "Air sports"),
        "ground": translate("QAmbit", "Ground sports"),
        "water": translate("QAmbit", "Water sports"),
        "vertical": translate("QAmbit", "Climbing & mountaineering"),
        "underwater": translate("QAmbit", "Underwater"),
    }.get(key, key)


def _group(project):
    root = project.layerTreeRoot()
    group = root.findGroup(GROUP_NAME)
    if group is None:
        group = root.insertGroup(0, GROUP_NAME)
    return group


def _find_layer(project, gpkg, name):
    """The project layer showing this store table, whatever its filter."""
    registry = QgsProviderRegistry.instance()
    target = os.path.abspath(gpkg)
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr":
            continue
        # The source gains "|subset=..." once the layer is filtered.
        parts = registry.decodeUri("ogr", layer.source())
        path = parts.get("path") or ""
        if path and os.path.abspath(path) == target and parts.get("layerName") == name:
            return layer
    return None


def _style_tracks(layer):
    categories = []
    for key, color in CATEGORY_COLORS.items():
        symbol = QgsLineSymbol.createSimple({"line_color": color, "line_width": "0.8"})
        categories.append(QgsRendererCategory(key, symbol, category_label(key)))
    layer.setRenderer(QgsCategorizedSymbolRenderer("category", categories))

    # Flown tracks keep their recorded altitude in the profile and 3D views
    elevation = layer.elevationProperties()
    elevation.setClamping(Qgis.AltitudeClamping.Absolute)
    elevation.setRespectLayerSymbology(True)
    _set_3d_renderer(layer)


def _set_3d_renderer(layer):
    try:
        from qgis._3d import (
            QgsLine3DSymbol,
            QgsPhongMaterialSettings,
            QgsVectorLayer3DRenderer,
        )
    except ImportError:
        return  # QGIS built without 3D
    symbol = QgsLine3DSymbol()
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    symbol.setRenderAsSimpleLines(True)
    symbol.setWidth(3.0)
    material = QgsPhongMaterialSettings()
    material.setAmbient(QColor(CATEGORY_COLORS["air"]))
    material.setDiffuse(QColor(CATEGORY_COLORS["air"]))
    symbol.setMaterialSettings(material)
    layer.setRenderer3D(QgsVectorLayer3DRenderer(symbol))


def _style_points(layer):
    symbol = QgsMarkerSymbol.createSimple(
        {"name": "circle", "size": "1.2", "color": "#f5a623", "outline_style": "no"}
    )
    layer.renderer().setSymbol(symbol)
    # The time slider replays a move fix by fix
    temporal = layer.temporalProperties()
    temporal.setIsActive(True)
    temporal.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
    temporal.setStartField("utc")
    elevation = layer.elevationProperties()
    elevation.setClamping(Qgis.AltitudeClamping.Absolute)


def _style_laps(layer):
    symbol = QgsMarkerSymbol.createSimple(
        {
            "name": "square",
            "size": "2.4",
            "color": "#ffffff",
            "outline_color": "#000000",
        }
    )
    layer.renderer().setSymbol(symbol)


def add_store_layers(gpkg, project=None):
    """
    Adds (or returns) the track, point and lap layers of the store.

    :return: dict layer name -> QgsVectorLayer
    """
    project = project or QgsProject.instance()
    if not os.path.exists(gpkg):
        return {}
    group = _group(project)
    styles = {
        store.TRACKS: _style_tracks,
        store.POINTS: _style_points,
        store.LAPS: _style_laps,
    }
    titles = {
        store.TRACKS: translate("QAmbit", "Tracks"),
        store.POINTS: translate("QAmbit", "Track points"),
        store.LAPS: translate("QAmbit", "Laps"),
    }
    layers = {}
    for name in (store.LAPS, store.POINTS, store.TRACKS):
        layer = _find_layer(project, gpkg, name)
        if layer is None:
            layer = QgsVectorLayer("{}|layername={}".format(gpkg, name), titles[name], "ogr")
            if not layer.isValid():
                continue
            styles[name](layer)
            project.addMapLayer(layer, False)
            node = group.insertLayer(0, layer)
            # Thousands of fixes per move: shown on demand
            node.setItemVisibilityChecked(name == store.TRACKS)
        layers[name] = layer
    return layers


def reload_store_layers(gpkg, project=None):
    project = project or QgsProject.instance()
    for name in (store.TRACKS, store.POINTS, store.LAPS):
        layer = _find_layer(project, gpkg, name)
        if layer is not None:
            layer.dataProvider().reloadData()
            layer.updateExtents()
            layer.triggerRepaint()


def filter_logs(gpkg, log_ids, project=None):
    """Shows only these logs on every store layer (None shows them all)."""
    project = project or QgsProject.instance()
    if log_ids:
        quoted = ",".join("'{}'".format(i.replace("'", "''")) for i in log_ids)
        subset = '"log_id" IN ({})'.format(quoted)
    else:
        subset = ""
    for name in (store.TRACKS, store.POINTS, store.LAPS):
        layer = _find_layer(project, gpkg, name)
        if layer is not None:
            layer.setSubsetString(subset)


def tracks_layer(gpkg, project=None):
    return _find_layer(project or QgsProject.instance(), gpkg, store.TRACKS)


class HcmgisMissing(RuntimeError):
    pass


def add_basemap(name, project=None):
    """
    Adds an HCMGIS basemap (raster or vector tiles) under the other layers.

    :raises HcmgisMissing: When the HCMGIS plugin is not installed or enabled
    :return: The added layer, or an existing layer of that name
    """
    project = project or QgsProject.instance()
    existing = project.mapLayersByName(name)
    if existing:
        return existing[0]
    try:
        from HCMGIS import hcmgis_library
    except ImportError as e:
        raise HcmgisMissing(
            translate(
                "QAmbit",
                "The HCMGIS plugin provides the basemaps; install and enable it.",
            )
        ) from e

    before = set(project.mapLayers())
    if name in hcmgis_library.basemap_names:
        hcmgis_library.hcmgis_basemap(name)
    elif name in getattr(hcmgis_library, "vectortiles_basemap_names", []):
        hcmgis_library.hcmgis_vectortiles_basemap(name)
    else:
        raise ValueError(translate("QAmbit", "HCMGIS has no basemap named {}.").format(name))
    added = [project.mapLayer(i) for i in set(project.mapLayers()) - before]
    if not added:
        raise RuntimeError(translate("QAmbit", "HCMGIS could not add the basemap {}.").format(name))

    # Basemaps go to the bottom of the layer tree
    root = project.layerTreeRoot()
    for layer in added:
        node = root.findLayer(layer.id())
        if node is not None:
            clone = node.clone()
            root.addChildNode(clone)
            node.parent().removeChildNode(node)
    return added[0]


def basemap_names():
    """The HCMGIS basemap names, or an empty list without HCMGIS."""
    try:
        from HCMGIS import hcmgis_library
    except ImportError:
        return []
    return list(hcmgis_library.basemap_names) + list(
        getattr(hcmgis_library, "vectortiles_basemap_names", [])
    )


def terrain_layer(project=None):
    """The Terrain Tiles elevation layer, added (hidden) when missing."""
    project = project or QgsProject.instance()
    for layer in project.mapLayersByName(TERRAIN_NAME):
        if isinstance(layer, QgsRasterLayer):
            return layer
    layer = QgsRasterLayer(dem.terrarium_uri(), TERRAIN_NAME, "wms")
    if not layer.isValid():
        return None
    project.addMapLayer(layer, False)
    node = _group(project).addLayer(layer)
    node.setItemVisibilityChecked(False)
    return layer


def add_dem_layer(path, project=None):
    project = project or QgsProject.instance()
    name = translate("QAmbit", "Copernicus DEM")
    for layer in project.mapLayers().values():
        if isinstance(layer, QgsRasterLayer) and layer.source() == path:
            return layer
    layer = QgsRasterLayer(path, name, "gdal")
    if not layer.isValid():
        raise RuntimeError(translate("QAmbit", "Cannot open the DEM {}.").format(path))
    project.addMapLayer(layer, False)
    node = _group(project).addLayer(layer)
    node.setItemVisibilityChecked(False)
    return layer


def set_project_terrain(layer, project=None):
    """Makes a DEM layer the terrain of new 3D views and of the elevation profile."""
    project = project or QgsProject.instance()
    provider = QgsRasterDemTerrainProvider()
    provider.setLayer(layer)
    project.elevationProperties().setTerrainProvider(provider)


def time_range_of(layer):
    """Time span of the visible point features, for the temporal controller."""
    index = layer.fields().indexOf("utc")
    if index < 0:
        return None
    lo, hi = layer.minimumValue(index), layer.maximumValue(index)
    if lo is None or hi is None or not lo.isValid() or not hi.isValid():
        return None
    return QgsDateTimeRange(lo, hi)


def find_group(project=None):
    root = (project or QgsProject.instance()).layerTreeRoot()
    node = root.findGroup(GROUP_NAME)
    return node if isinstance(node, QgsLayerTreeGroup) else None
