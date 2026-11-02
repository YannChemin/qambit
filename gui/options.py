"""
MODULE:    qambit.gui.options
AUTHOR(S): Yann Chemin
PURPOSE:   The QAmbit page of the QGIS options dialog.
SPDX-License-Identifier: Unlicense
"""

from qgis.gui import QgsFileWidget, QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt.QtCore import QT_TRANSLATE_NOOP, QCoreApplication
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
)

from .. import qgis_layers, settings

PATHS = (
    (
        "cli_path",
        QT_TRANSLATE_NOOP("QAmbit", "openambit-cli (empty: find it):"),
        QgsFileWidget.StorageMode.GetFile,
    ),
    (
        "data_dir",
        QT_TRANSLATE_NOOP("QAmbit", "openambit folder (logs, sport modes, plans):"),
        QgsFileWidget.StorageMode.GetDirectory,
    ),
    (
        "gpkg",
        QT_TRANSLATE_NOOP("QAmbit", "Move store (GeoPackage):"),
        QgsFileWidget.StorageMode.SaveFile,
    ),
    (
        "orbit_script",
        QT_TRANSLATE_NOOP("QAmbit", "GPS orbit script (rinex2ubx_ambit.py):"),
        QgsFileWidget.StorageMode.GetFile,
    ),
    (
        "orbit_file",
        QT_TRANSLATE_NOOP("QAmbit", "GPS orbit file:"),
        QgsFileWidget.StorageMode.SaveFile,
    ),
    (
        "dem_cache",
        QT_TRANSLATE_NOOP("QAmbit", "Elevation cache folder:"),
        QgsFileWidget.StorageMode.GetDirectory,
    ),
)
FLAGS = (
    ("read_logs", QT_TRANSLATE_NOOP("QAmbit", "Read new moves when syncing")),
    ("sync_time", QT_TRANSLATE_NOOP("QAmbit", "Set the watch time when syncing")),
    ("sync_orbit", QT_TRANSLATE_NOOP("QAmbit", "Write the GPS orbit when syncing")),
    ("sync_on_connect", QT_TRANSLATE_NOOP("QAmbit", "Sync when a watch is plugged in")),
    ("air_sports_3d", QT_TRANSLATE_NOOP("QAmbit", "Open air sports in a 3D view")),
)
DEM_SOURCES = (
    (
        "auto",
        QT_TRANSLATE_NOOP("QAmbit", "IGN LiDAR HD where available (France), else Copernicus"),
    ),
    ("lidarhd", QT_TRANSLATE_NOOP("QAmbit", "IGN LiDAR HD only")),
    ("copernicus", QT_TRANSLATE_NOOP("QAmbit", "Copernicus DEM only")),
)
LIDARHD_PRODUCTS = (
    (
        "mns",
        QT_TRANSLATE_NOOP("QAmbit", "Surface model (MNS, with trees and buildings)"),
    ),
    ("mnt", QT_TRANSLATE_NOOP("QAmbit", "Terrain model (MNT, bare earth)")),
)


def _t(text):
    return QCoreApplication.translate("QAmbit", text)


class OptionsPage(QgsOptionsPageWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        files = QGroupBox(self.tr("Files"))
        form = QFormLayout(files)
        self.paths = {}
        for key, label, mode in PATHS:
            widget = QgsFileWidget()
            widget.setStorageMode(mode)
            widget.setFilePath(settings.value(key))
            form.addRow(_t(label), widget)
            self.paths[key] = widget
        layout.addWidget(files)

        sync = QGroupBox(self.tr("Watch"))
        form = QFormLayout(sync)
        self.flags = {}
        for key, label in FLAGS:
            box = QCheckBox(_t(label))
            box.setChecked(settings.value(key))
            form.addRow(box)
            self.flags[key] = box
        layout.addWidget(sync)

        maps = QGroupBox(self.tr("Maps"))
        form = QFormLayout(maps)
        self.dem_source = self._choice(DEM_SOURCES, settings.value("dem_source"))
        self.product = self._choice(LIDARHD_PRODUCTS, settings.value("lidarhd_product"))
        names = qgis_layers.basemap_names()
        self.basemap_2d = QComboBox()
        self.basemap_3d = QComboBox()
        for combo, key in (
            (self.basemap_2d, "basemap_2d"),
            (self.basemap_3d, "basemap_3d"),
        ):
            combo.addItems(names)
            combo.setCurrentText(settings.value(key))
            combo.setEnabled(bool(names))
        form.addRow(self.tr("Detailed terrain:"), self.dem_source)
        form.addRow(self.tr("LiDAR HD model:"), self.product)
        form.addRow(self.tr("2D basemap (HCMGIS):"), self.basemap_2d)
        form.addRow(self.tr("3D drape (HCMGIS):"), self.basemap_3d)
        layout.addWidget(maps)
        layout.addStretch(1)

    def _choice(self, items, current):
        combo = QComboBox()
        for value, label in items:
            combo.addItem(_t(label), value)
        index = combo.findData(current)
        combo.setCurrentIndex(max(index, 0))
        return combo

    def apply(self):
        for key, widget in self.paths.items():
            settings.set_value(key, widget.filePath())
        for key, box in self.flags.items():
            settings.set_value(key, box.isChecked())
        settings.set_value("dem_source", self.dem_source.currentData())
        settings.set_value("lidarhd_product", self.product.currentData())
        if self.basemap_2d.isEnabled():
            settings.set_value("basemap_2d", self.basemap_2d.currentText())
            settings.set_value("basemap_3d", self.basemap_3d.currentText())


class OptionsFactory(QgsOptionsWidgetFactory):
    def __init__(self, icon):
        super().__init__("QAmbit", icon)

    def createWidget(self, parent):
        return OptionsPage(parent)
