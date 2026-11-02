"""
MODULE:    qambit.plugin
AUTHOR(S): Yann Chemin
PURPOSE:   QAmbit, the QGIS side of openambit2: syncs a Suunto Ambit through
           openambit-cli, keeps its moves in a GeoPackage and shows them with
           QGIS's own map, 3D, elevation profile and time tools.
SPDX-License-Identifier: Unlicense
"""

import json
import os
import tempfile

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsSettings,
)
from qgis.PyQt.QtCore import (
    QCoreApplication,
    QFileSystemWatcher,
    Qt,
    QTimer,
    QTranslator,
)
from qgis.PyQt.QtGui import QIcon

from . import qgis_layers, settings
from .core import cli, store
from .core.device import find_watches
from .core.logparser import find_logs
from .tasks import CliTask, DemTask, ImportTask, OrbitTask

PLUGIN_DIR = os.path.dirname(__file__)
MENU = "&QAmbit"
# A margin around the tracks for the terrain and the 3D scene, in degrees.
BOX_MARGIN = 0.01


def translate(context, text):
    return QCoreApplication.translate(context, text)


def _utm_crs(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return QgsCoordinateReferenceSystem("EPSG:{}".format((32600 if lat >= 0 else 32700) + zone))


class QAmbitPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.translator = None
        self.dock = None
        self.toolbar = None
        self.actions = []
        self.options_factory = None
        self.provider = None
        self.watcher = None
        self.watch_timer = None
        self.watches = []
        self.busy = False
        # A QgsTask must stay referenced until it ends.
        self.tasks = []
        self._load_translation()

    # Set-up

    def _load_translation(self):
        locale = QgsSettings().value("locale/userLocale", "") or ""
        qm = os.path.join(PLUGIN_DIR, "i18n", "qambit_{}.qm".format(locale[:2]))
        if os.path.exists(qm):
            self.translator = QTranslator()
            if self.translator.load(qm):
                QCoreApplication.installTranslator(self.translator)

    def initGui(self):
        from .gui.dock import AmbitDock
        from .gui.options import OptionsFactory

        icon = QIcon(os.path.join(PLUGIN_DIR, "icons", "icon.svg"))
        self.panel_action = self._action(
            icon, translate("QAmbit", "QAmbit panel"), self.toggle_dock, checkable=True
        )
        self.sync_action = self._action(
            QgsApplication.getThemeIcon("/mActionRefresh.svg"),
            translate("QAmbit", "Sync Ambit watch"),
            self.sync,
        )
        self.import_action = self._action(
            QgsApplication.getThemeIcon("/mActionAddOgrLayer.svg"),
            translate("QAmbit", "Import openambit logs"),
            self.import_logs,
        )
        self.toolbar = self.iface.addToolBar("QAmbit")
        self.toolbar.setObjectName("QAmbitToolbar")
        for action in (self.panel_action, self.sync_action):
            self.toolbar.addAction(action)
        for action in self.actions:
            self.iface.addPluginToMenu(MENU, action)

        self.dock = AmbitDock(self.iface.mainWindow())
        self.dock.setVisible(False)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._dock_visibility)
        self.dock.syncRequested.connect(self.sync)
        self.dock.infoRequested.connect(self.read_info)
        self.dock.importRequested.connect(self.import_logs)
        self.dock.sportModesRequested.connect(self.edit_sport_modes)
        self.dock.trainingPlansRequested.connect(self.edit_training_plans)
        self.dock.orbitRequested.connect(self.update_orbit)
        self.dock.view3dRequested.connect(lambda: self.open_3d(self.dock.selected_log_ids()))
        self.dock.profileRequested.connect(self.open_profile)
        self.dock.demRequested.connect(self.fetch_terrain)
        self.dock.basemapRequested.connect(self.add_basemap)
        self.dock.selectionChanged.connect(self._selection_changed)
        self.dock.filterChanged.connect(
            lambda _: self._selection_changed(self.dock.selected_log_ids())
        )
        self.dock.set_basemaps(qgis_layers.basemap_names(), settings.value("basemap_2d"))

        self.options_factory = OptionsFactory(icon)
        self.options_factory.setTitle("QAmbit")
        self.iface.registerOptionsWidgetFactory(self.options_factory)

        from .processing_provider.provider import QAmbitProvider

        self.provider = QAmbitProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        # Watches come and go as hidraw nodes in /dev.
        self.watch_timer = QTimer()
        self.watch_timer.setSingleShot(True)
        self.watch_timer.setInterval(1000)
        self.watch_timer.timeout.connect(self._scan_watches)
        self.watcher = QFileSystemWatcher(["/dev"])
        self.watcher.directoryChanged.connect(lambda _: self.watch_timer.start())
        self._scan_watches(first=True)

    def _action(self, icon, text, slot, checkable=False):
        from qgis.PyQt.QtWidgets import QAction

        action = QAction(icon, text, self.iface.mainWindow())
        action.setCheckable(checkable)
        action.triggered.connect(slot)
        self.actions.append(action)
        return action

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
        if self.toolbar is not None:
            self.toolbar.deleteLater()
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
        if self.options_factory is not None:
            self.iface.unregisterOptionsWidgetFactory(self.options_factory)
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        if self.watcher is not None:
            self.watcher.directoryChanged.disconnect()
        if self.translator is not None:
            QCoreApplication.removeTranslator(self.translator)

    # Messages and tasks

    def _info(self, text, level=Qgis.MessageLevel.Info, duration=6):
        self.iface.messageBar().pushMessage("QAmbit", text, level, duration)

    def _error(self, text):
        self._info(text, Qgis.MessageLevel.Critical, 0)

    def _run(self, task):
        self.tasks.append(task)
        callback = task.on_finished

        def done(t, ok):
            if t in self.tasks:
                self.tasks.remove(t)
            if callback:
                callback(t, ok)

        task.on_finished = done
        QgsApplication.taskManager().addTask(task)

    def _set_busy(self, busy):
        self.busy = busy
        self.sync_action.setEnabled(not busy)
        if self.dock:
            self.dock.set_busy(busy)
            if not busy:
                self.dock.set_watch(self._watch_text(), bool(self.watches))

    def _cli(self):
        try:
            return cli.find_cli(settings.value("cli_path"))
        except FileNotFoundError as e:
            self._error(str(e))
            return None

    # The panel

    def toggle_dock(self, checked):
        self.dock.setVisible(checked)

    def _dock_visibility(self, visible):
        self.panel_action.setChecked(visible)
        if visible:
            self.refresh_list()

    def refresh_list(self):
        if self.dock is not None:
            try:
                self.dock.set_logs(store.list_tracks(settings.value("gpkg")))
            except RuntimeError as e:
                self._error(translate("QAmbit", "Cannot read the move store: {}").format(e))

    def _selection_changed(self, log_ids):
        gpkg = settings.value("gpkg")
        layers = qgis_layers.add_store_layers(gpkg)
        if not layers:
            return
        if self.dock.only_selected.isChecked():
            qgis_layers.filter_logs(gpkg, log_ids)
        else:
            qgis_layers.filter_logs(gpkg, None)
        if log_ids:
            self._zoom_to(log_ids)

    def _zoom_to(self, log_ids, margin=BOX_MARGIN):
        box = store.tracks_box(settings.value("gpkg"), log_ids)
        if box is None:
            return None
        west, south, east, north = box
        rect = QgsRectangle(west - margin, south - margin, east + margin, north + margin)
        canvas = self.iface.mapCanvas()
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            canvas.mapSettings().destinationCrs(),
            QgsProject.instance(),
        )
        canvas.setExtent(transform.transformBoundingBox(rect))
        canvas.refresh()
        return rect

    # The watch

    def _watch_text(self):
        if not self.watches:
            return translate("QAmbit", "No watch connected")
        return ", ".join(w["name"] for w in self.watches)

    def _scan_watches(self, first=False):
        before = {w["node"] for w in self.watches}
        self.watches = find_watches()
        if self.dock is not None and not self.busy:
            self.dock.set_watch(self._watch_text(), bool(self.watches))
        new = [w for w in self.watches if w["node"] not in before]
        if new and not first:
            self._info(translate("QAmbit", "{} connected.").format(new[0]["name"]))
            if settings.value("sync_on_connect") and not self.busy:
                # The watch needs a moment before it answers.
                QTimer.singleShot(2000, self.sync)

    def read_info(self):
        path = self._cli()
        if path is None or self.busy:
            return
        self._set_busy(True)

        def done(task, ok):
            self._set_busy(False)
            info = task.output.info
            if not ok or not info:
                self._error(translate("QAmbit", "Cannot read the watch: {}").format(task.error))
                return
            text = translate(
                "QAmbit",
                "{name} ({model}), serial {serial}, firmware {fw}, battery {charge} %",
            ).format(
                name=info.get("name", ""),
                model=info.get("model", ""),
                serial=info.get("serial", ""),
                fw=info.get("fw_version", ""),
                charge=info.get("charge", "?"),
            )
            self.dock.set_watch(text, True)
            if not info.get("supported", True):
                self._info(
                    translate("QAmbit", "openambit does not fully support this watch."),
                    Qgis.MessageLevel.Warning,
                )

        self._run(
            CliTask(
                translate("QAmbit", "Reading the Ambit watch"),
                path,
                cli.info_args(),
                done,
            )
        )

    def sync(self):
        """Orbit file, then the watch (moves, time, orbit), then the import."""
        path = self._cli()
        if path is None or self.busy:
            return
        self._set_busy(True)
        orbit_file = settings.value("orbit_file")
        script = settings.value("orbit_script")
        if settings.value("sync_orbit") and os.path.exists(script):

            def orbit_done(task, ok):
                if not ok:
                    self._info(
                        translate(
                            "QAmbit",
                            "GPS orbit not updated ({}); the watch keeps its previous one.",
                        ).format(task.error),
                        Qgis.MessageLevel.Warning,
                    )
                self._sync_watch(path, orbit_file if ok or os.path.exists(orbit_file) else None)

            self._run(
                OrbitTask(
                    translate("QAmbit", "Updating the GPS orbit"),
                    script,
                    orbit_file,
                    orbit_done,
                )
            )
        else:
            if settings.value("sync_orbit"):
                self._info(
                    translate("QAmbit", "GPS orbit script not found: {}").format(script),
                    Qgis.MessageLevel.Warning,
                )
            self._sync_watch(path, None)

    def _sync_watch(self, path, orbit_file):
        args = cli.sync_args(settings.value("read_logs"), settings.value("sync_time"), orbit_file)

        def done(task, ok):
            if not ok:
                self._set_busy(False)
                self._error(translate("QAmbit", "Sync failed: {}").format(task.error))
                return
            self._info(
                translate("QAmbit", "Watch synced: {} new moves.").format(task.output.stored_logs),
                Qgis.MessageLevel.Success,
            )
            if settings.value("read_logs"):
                self._import(auto_3d=True)
            else:
                self._set_busy(False)

        self._run(CliTask(translate("QAmbit", "Syncing the Ambit watch"), path, args, done))

    def update_orbit(self):
        script = settings.value("orbit_script")
        if not os.path.exists(script):
            self._error(translate("QAmbit", "GPS orbit script not found: {}").format(script))
            return

        def done(task, ok):
            if ok:
                self._info(
                    translate(
                        "QAmbit",
                        "GPS orbit file updated; it goes to the watch at the next sync.",
                    ),
                    Qgis.MessageLevel.Success,
                )
            else:
                self._error(translate("QAmbit", "GPS orbit not updated: {}").format(task.error))

        self._run(
            OrbitTask(
                translate("QAmbit", "Updating the GPS orbit"),
                script,
                settings.value("orbit_file"),
                done,
            )
        )

    def _write_json(self, data, args_for, description):
        path = self._cli()
        if path is None or self.busy:
            return
        if not self.watches:
            self._error(translate("QAmbit", "Plug in the watch first."))
            return
        fd, tmp = tempfile.mkstemp(prefix="qambit_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        self._set_busy(True)

        def done(task, ok):
            self._set_busy(False)
            os.unlink(tmp)
            if ok:
                self._info(
                    translate("QAmbit", "{}: done.").format(description),
                    Qgis.MessageLevel.Success,
                )
            else:
                self._error(translate("QAmbit", "{} failed: {}").format(description, task.error))

        self._run(CliTask(description, path, args_for(tmp), done))

    def edit_sport_modes(self):
        from .gui.sportmodes import SportModesDialog

        try:
            dialog = SportModesDialog(settings.sport_modes_path(), self.iface.mainWindow())
        except (OSError, ValueError) as e:
            self._error(str(e))
            return
        dialog.writeRequested.connect(
            lambda modes: self._write_json(
                modes,
                cli.sport_modes_args,
                translate("QAmbit", "Writing the sport modes"),
            )
        )
        dialog.exec()

    def edit_training_plans(self):
        from .gui.trainingplan import TrainingPlanDialog

        try:
            dialog = TrainingPlanDialog(settings.training_plans_path(), self.iface.mainWindow())
        except (OSError, ValueError) as e:
            self._error(str(e))
            return
        dialog.writeRequested.connect(
            lambda plan: self._write_json(
                plan,
                cli.training_plan_args,
                translate("QAmbit", "Writing the training plan"),
            )
        )
        dialog.exec()

    # Moves

    def import_logs(self, force=False):
        if self.busy:
            return
        self._set_busy(True)
        self._import(auto_3d=False, force=bool(force))

    def _import(self, auto_3d, force=False):
        paths = find_logs(settings.value("data_dir"))
        gpkg = settings.value("gpkg")

        def done(task, ok):
            self._set_busy(False)
            if not ok:
                self._error(translate("QAmbit", "Import failed: {}").format(task.error))
                return
            result = task.result
            imported = result["imported"]
            self._info(
                translate("QAmbit", "{} moves imported, {} unchanged, {} without track.").format(
                    len(imported), len(result["unchanged"]), len(result["skipped"])
                ),
                Qgis.MessageLevel.Success if imported else Qgis.MessageLevel.Info,
            )
            qgis_layers.add_store_layers(gpkg)
            qgis_layers.reload_store_layers(gpkg)
            self.refresh_list()
            if auto_3d and imported and settings.value("air_sports_3d"):
                flights = [
                    r["log_id"]
                    for r in store.list_tracks(gpkg)
                    if r["log_id"] in imported and r["prefers_3d"]
                ]
                if flights:
                    self.open_3d(flights)

        self._run(
            ImportTask(
                translate("QAmbit", "Importing the Ambit moves"),
                paths,
                gpkg,
                force,
                done,
            )
        )

    # Maps

    def add_basemap(self, name):
        try:
            qgis_layers.add_basemap(name)
        except qgis_layers.HcmgisMissing as e:
            self._error(str(e))
        except (ValueError, RuntimeError) as e:
            self._error(str(e))

    def _prepare_3d_crs(self, rect):
        """A projected CRS for the 3D scene; 3D views cannot use degrees."""
        project = QgsProject.instance()
        crs = project.crs()
        if crs.isValid() and not crs.isGeographic() and crs.authid() != "EPSG:3857":
            return
        center = rect.center()
        utm = _utm_crs(center.x(), center.y())
        project.setCrs(utm)
        self._info(
            translate(
                "QAmbit",
                "Project CRS set to {} so that the 3D view keeps true distances and heights.",
            ).format(utm.authid())
        )

    def open_3d(self, log_ids=None):
        gpkg = settings.value("gpkg")
        if not qgis_layers.add_store_layers(gpkg):
            self._error(translate("QAmbit", "No moves yet: sync the watch or import the logs."))
            return
        log_ids = log_ids or None
        if self.dock and self.dock.only_selected.isChecked():
            qgis_layers.filter_logs(gpkg, log_ids)
        box = store.tracks_box(gpkg, log_ids)
        if box is None:
            return
        west, south, east, north = box
        rect = QgsRectangle(
            west - BOX_MARGIN, south - BOX_MARGIN, east + BOX_MARGIN, north + BOX_MARGIN
        )
        self._prepare_3d_crs(rect)

        project = QgsProject.instance()
        if project.elevationProperties().terrainProvider().type() != "raster":
            layer = qgis_layers.terrain_layer()
            if layer is not None:
                qgis_layers.set_project_terrain(layer)
        try:
            qgis_layers.add_basemap(settings.value("basemap_3d"))
        except qgis_layers.HcmgisMissing as e:
            self._info(str(e), Qgis.MessageLevel.Warning)
        except (ValueError, RuntimeError) as e:
            self._info(str(e), Qgis.MessageLevel.Warning)

        # QGIS builds the 3D scene over the project extent; keep it to the moves.
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(wgs84, project.crs(), project)
        project.viewSettings().setPresetFullExtent(
            QgsReferencedRectangle(transform.transformBoundingBox(rect), project.crs())
        )
        self._zoom_to(log_ids)
        canvas = self.iface.createNewMapCanvas3D(translate("QAmbit", "Ambit 3D"))
        if canvas is None:
            self._error(translate("QAmbit", "This QGIS has no 3D views."))

    def fetch_terrain(self):
        gpkg = settings.value("gpkg")
        log_ids = self.dock.selected_log_ids() if self.dock else []
        box = store.tracks_box(gpkg, log_ids or None)
        if box is None:
            self._error(translate("QAmbit", "No moves yet: sync the watch or import the logs."))
            return
        west, south, east, north = box
        box = (
            west - BOX_MARGIN,
            south - BOX_MARGIN,
            east + BOX_MARGIN,
            north + BOX_MARGIN,
        )

        def done(task, ok):
            if not ok:
                self._error(translate("QAmbit", "Terrain download failed: {}").format(task.error))
                return
            try:
                layer = qgis_layers.add_dem_layer(task.path)
            except RuntimeError as e:
                self._error(str(e))
                return
            qgis_layers.set_project_terrain(layer)
            source = (
                translate("QAmbit", "IGN LiDAR HD")
                if task.used == "lidarhd"
                else translate("QAmbit", "Copernicus DEM")
            )
            note = " ({})".format(task.note) if task.note else ""
            self._info(
                translate(
                    "QAmbit",
                    "{} is now the terrain of new 3D views and of the elevation profile.",
                ).format(source)
                + note,
                Qgis.MessageLevel.Success,
            )

        self._run(
            DemTask(
                translate("QAmbit", "Downloading the terrain"),
                box,
                settings.value("dem_cache"),
                settings.value("dem_source"),
                settings.value("lidarhd_product"),
                done,
            )
        )

    def open_profile(self):
        """Opens an elevation profile along the (first) selected move."""
        from qgis.gui import QgsElevationProfileCanvas

        window = self.iface.mainWindow()
        before = set(window.findChildren(QgsElevationProfileCanvas))
        action = window.findChild(type(self.panel_action), "mActionElevationProfile")
        if action is None:
            self._error(translate("QAmbit", "This QGIS has no elevation profile."))
            return
        action.trigger()
        log_ids = self.dock.selected_log_ids() if self.dock else []
        layer = qgis_layers.tracks_layer(settings.value("gpkg"))
        if not log_ids or layer is None:
            self._info(
                translate("QAmbit", "Select a move in the QAmbit panel to draw its profile.")
            )
            return
        created = [c for c in window.findChildren(QgsElevationProfileCanvas) if c not in before]
        if not created:
            return
        canvas = created[0]
        feature = next(
            layer.getFeatures("\"log_id\" = '{}'".format(log_ids[0].replace("'", "''"))),
            None,
        )
        if feature is None:
            return
        project = QgsProject.instance()
        geometry = QgsGeometry(feature.geometry())
        geometry.transform(QgsCoordinateTransform(layer.crs(), project.crs(), project))
        curve = geometry.constGet().clone()
        curve.dropZValue()
        curve.dropMValue()
        canvas.setCrs(project.crs())
        canvas.setProfileCurve(curve)
        canvas.refresh()
