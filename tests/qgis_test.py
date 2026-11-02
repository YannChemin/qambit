"""
Headless QGIS tests: layers, dialogs, Processing algorithms and the plugin
against a mocked QGIS interface. Run with QT_QPA_PLATFORM=offscreen.
"""

import json
import os
import shutil
import sys

import pytest

qgis_core = pytest.importorskip("qgis.core")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import Qgis, QgsApplication, QgsProject  # noqa: E402


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.testing import start_app

    return start_app()


@pytest.fixture
def store_gpkg(tmp_path, flight_log, qgis_app):
    from qambit.core import store

    gpkg = str(tmp_path / "store.gpkg")
    store.import_logs([flight_log], gpkg)
    yield gpkg
    QgsProject.instance().clear()


@pytest.fixture
def settings(tmp_path, store_gpkg, flight_log):
    from qambit import settings

    data = tmp_path / "openambit"
    data.mkdir()
    shutil.copy(flight_log, data)
    values = {"gpkg": store_gpkg, "data_dir": str(data), "dem_cache": str(tmp_path / "dem")}
    saved = {k: settings.value(k) for k in values}
    for k, v in values.items():
        settings.set_value(k, v)
    yield settings
    for k, v in saved.items():
        settings.set_value(k, v)


def test_store_layers(store_gpkg):
    from qambit import qgis_layers
    from qambit.core import store

    layers = qgis_layers.add_store_layers(store_gpkg)
    assert set(layers) == {store.TRACKS, store.POINTS, store.LAPS}
    tracks = layers[store.TRACKS]
    assert tracks.featureCount() == 1
    assert tracks.renderer().type() == "categorizedSymbol"
    assert tracks.elevationProperties().clamping() == Qgis.AltitudeClamping.Absolute
    points = layers[store.POINTS]
    assert points.temporalProperties().isActive()
    span = qgis_layers.time_range_of(points)
    assert span.begin().toString("HH:mm:ss") == "08:00:03"
    # Adding again returns the same layers.
    assert qgis_layers.add_store_layers(store_gpkg)[store.TRACKS] is tracks
    assert qgis_layers.find_group().name() == qgis_layers.GROUP_NAME

    # Counted by iterating: in some sandboxes the GeoPackage count probe of a
    # filtered layer fails (featureCount() -1) although the filter works.
    qgis_layers.filter_logs(store_gpkg, ["nothing"])
    assert sum(1 for _ in tracks.getFeatures()) == 0
    assert sum(1 for _ in points.getFeatures()) == 0
    qgis_layers.filter_logs(store_gpkg, None)
    assert sum(1 for _ in tracks.getFeatures()) == 1


def test_terrain(store_gpkg):
    from qambit import qgis_layers

    layer = qgis_layers.terrain_layer()
    assert layer is not None and layer.isValid()
    assert qgis_layers.terrain_layer() is layer
    qgis_layers.set_project_terrain(layer)
    provider = QgsProject.instance().elevationProperties().terrainProvider()
    assert provider.type() == "raster"
    assert provider.layer() is layer


def test_sport_modes_dialog(tmp_path, qgis_app):
    from qambit.gui.sportmodes import SportModesDialog

    path = str(tmp_path / "sport_modes.json")
    dialog = SportModesDialog(path)
    dialog._add_blank()
    dialog._add("Paragliding", 92, 1, 1, 1)
    dialog.name.setText("Parapente")
    sent = []
    dialog.writeRequested.connect(sent.append)
    dialog._write()
    (modes,) = sent
    assert [m["Name"] for m in modes] == ["New mode", "Parapente"]
    assert modes[1]["AltiBaroMode"] == 1
    assert json.load(open(path)) == modes
    dialog.list.setCurrentRow(0)
    dialog._remove()
    assert [m["Name"] for m in dialog.modes] == ["Parapente"]


def test_training_plan_dialog(tmp_path, qgis_app):
    from qambit.gui.trainingplan import TrainingPlanDialog

    path = str(tmp_path / "training_plans.json")
    dialog = TrainingPlanDialog(path)
    dialog._add_entry()
    dialog._add_repeat()
    sent = []
    dialog.writeRequested.connect(sent.append)
    dialog._write()
    (plan,) = sent
    steps = plan["entries"][0]["workout"]["steps"]
    assert [s["type"]["typeName"] for s in steps] == [
        "interval",
        "repeatStart",
        "interval",
        "recovery",
        "repeatEnd",
    ]
    assert steps[1]["type"]["value"] == 2
    assert json.load(open(path))[0]["name"] == plan["name"]


def test_options_page(settings, qgis_app):
    from qambit.gui.options import OptionsPage

    page = OptionsPage()
    page.dem_source.setCurrentIndex(page.dem_source.findData("copernicus"))
    page.apply()
    assert settings.value("dem_source") == "copernicus"
    settings.set_value("dem_source", "auto")


def test_processing_import(settings, tmp_path, qgis_app):
    sys.path.append("/usr/share/qgis/python/plugins")
    import processing
    from processing.core.Processing import Processing

    from qambit.processing_provider.provider import QAmbitProvider

    Processing.initialize()
    provider = QAmbitProvider()
    QgsApplication.processingRegistry().addProvider(provider)
    try:
        out = str(tmp_path / "p.gpkg")
        result = processing.run(
            "qambit:importlogs", {"FOLDER": settings.value("data_dir"), "GPKG": out, "FORCE": False}
        )
        assert result["IMPORTED"] == 1
        assert os.path.exists(out)
        assert QgsApplication.processingRegistry().algorithmById("qambit:downloadterrain")
    finally:
        QgsApplication.processingRegistry().removeProvider(provider)


def test_plugin_loads(settings, qgis_app):
    from qgis.testing.mocked import get_iface

    import qambit

    iface = get_iface()
    plugin = qambit.classFactory(iface)
    plugin.initGui()
    try:
        plugin.dock.setVisible(True)
        plugin.refresh_list()
        assert plugin.dock.tree.topLevelItemCount() == 1
        plugin.dock.tree.topLevelItem(0).setSelected(True)
        assert plugin.dock.selected_log_ids() == ["log_TEST000000000001_2026_07_01_10_00_00"]
        # Selecting a move loads the layers.
        assert QgsProject.instance().mapLayersByName("Tracks")
    finally:
        plugin.unload()


def test_open_3d(settings, qgis_app):
    from qgis.testing.mocked import get_iface

    import qambit

    iface = get_iface()
    plugin = qambit.classFactory(iface)
    plugin.initGui()
    try:
        project = QgsProject.instance()
        project.setCrs(qgis_core.QgsCoordinateReferenceSystem("EPSG:4326"))
        plugin.open_3d(["log_TEST000000000001_2026_07_01_10_00_00"])
        # Degrees cannot make a 3D scene: the project moves to UTM 32N.
        assert project.crs().authid() == "EPSG:32632"
        assert project.elevationProperties().terrainProvider().type() == "raster"
        extent = project.viewSettings().presetFullExtent()
        assert extent.crs().authid() == "EPSG:32632"
        assert 0 < extent.width() < 5000
        assert iface.createNewMapCanvas3D.called
    finally:
        plugin.unload()
