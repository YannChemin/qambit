"""
MODULE:    qambit.gui.dock
AUTHOR(S): Yann Chemin
PURPOSE:   The QAmbit panel: watch status and sync, the list of moves, and
           the shortcuts to the 3D view, elevation, basemaps and editors.
SPDX-License-Identifier: Unlicense
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..qgis_layers import CATEGORY_COLORS, category_label


def _duration(seconds):
    seconds = int(seconds or 0)
    return "{}:{:02d}:{:02d}".format(seconds // 3600, seconds % 3600 // 60, seconds % 60)


class AmbitDock(QDockWidget):
    """Emits requests; the plugin controller carries them out."""

    syncRequested = pyqtSignal()
    infoRequested = pyqtSignal()
    importRequested = pyqtSignal()
    sportModesRequested = pyqtSignal()
    trainingPlansRequested = pyqtSignal()
    orbitRequested = pyqtSignal()
    view3dRequested = pyqtSignal()
    profileRequested = pyqtSignal()
    demRequested = pyqtSignal()
    basemapRequested = pyqtSignal(str)
    selectionChanged = pyqtSignal(list)
    filterChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Ambit watch"))
        self.setObjectName("QAmbitDock")
        body = QWidget()
        layout = QVBoxLayout(body)

        watch = QGroupBox(self.tr("Watch"))
        wl = QGridLayout(watch)
        self.status = QLabel(self.tr("No watch connected"))
        self.status.setWordWrap(True)
        self.sync_button = QPushButton(self.tr("Sync"))
        self.sync_button.setToolTip(
            self.tr(
                "Read the new moves, set the time and write the GPS orbit, as set in the options"
            )
        )
        self.info_button = QPushButton(self.tr("Battery"))
        self.info_button.setToolTip(self.tr("Read the device information and charge"))
        wl.addWidget(self.status, 0, 0, 1, 2)
        wl.addWidget(self.sync_button, 1, 0)
        wl.addWidget(self.info_button, 1, 1)
        self.modes_button = QPushButton(self.tr("Sport modes..."))
        self.plans_button = QPushButton(self.tr("Training plans..."))
        self.orbit_button = QPushButton(self.tr("Update GPS orbit"))
        wl.addWidget(self.modes_button, 2, 0)
        wl.addWidget(self.plans_button, 2, 1)
        wl.addWidget(self.orbit_button, 3, 0, 1, 2)
        layout.addWidget(watch)

        moves = QGroupBox(self.tr("Moves"))
        ml = QVBoxLayout(moves)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            [
                self.tr("Date"),
                self.tr("Activity"),
                self.tr("km"),
                self.tr("Duration"),
                self.tr("Ascent"),
            ]
        )
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        ml.addWidget(self.tree)
        self.only_selected = QCheckBox(self.tr("Show only the selected moves"))
        ml.addWidget(self.only_selected)
        row = QHBoxLayout()
        self.import_button = QPushButton(self.tr("Import logs"))
        self.import_button.setToolTip(
            self.tr("Read the logs of the openambit folder into the map layers")
        )
        row.addWidget(self.import_button)
        ml.addLayout(row)
        layout.addWidget(moves, 1)

        view = QGroupBox(self.tr("View"))
        vl = QGridLayout(view)
        self.view3d_button = QPushButton(self.tr("3D view"))
        self.view3d_button.setToolTip(
            self.tr("Open a 3D view of the selected moves over the relief")
        )
        self.profile_button = QPushButton(self.tr("Elevation profile"))
        self.dem_button = QPushButton(self.tr("Detailed terrain"))
        self.dem_button.setToolTip(
            self.tr(
                "Download the elevation around the selected moves (IGN LiDAR HD 50 cm in France, Copernicus elsewhere) and use it as terrain"
            )
        )
        self.basemap = QComboBox()
        self.basemap_button = QPushButton(self.tr("Add basemap"))
        vl.addWidget(self.view3d_button, 0, 0)
        vl.addWidget(self.profile_button, 0, 1)
        vl.addWidget(self.dem_button, 1, 0, 1, 2)
        vl.addWidget(self.basemap, 2, 0)
        vl.addWidget(self.basemap_button, 2, 1)
        layout.addWidget(view)
        self.setWidget(body)

        self.sync_button.clicked.connect(self.syncRequested)
        self.info_button.clicked.connect(self.infoRequested)
        self.import_button.clicked.connect(self.importRequested)
        self.modes_button.clicked.connect(self.sportModesRequested)
        self.plans_button.clicked.connect(self.trainingPlansRequested)
        self.orbit_button.clicked.connect(self.orbitRequested)
        self.view3d_button.clicked.connect(self.view3dRequested)
        self.profile_button.clicked.connect(self.profileRequested)
        self.dem_button.clicked.connect(self.demRequested)
        self.basemap_button.clicked.connect(
            lambda: self.basemapRequested.emit(self.basemap.currentText())
        )
        self.tree.itemSelectionChanged.connect(
            lambda: self.selectionChanged.emit(self.selected_log_ids())
        )
        self.only_selected.toggled.connect(self.filterChanged)

    def set_basemaps(self, names, current):
        self.basemap.clear()
        if not names:
            self.basemap.addItem(self.tr("(install HCMGIS for basemaps)"))
            self.basemap.setEnabled(False)
            self.basemap_button.setEnabled(False)
            return
        self.basemap.addItems(names)
        self.basemap.setCurrentText(current)

    def set_watch(self, text, connected):
        self.status.setText(text)
        for button in (self.sync_button, self.info_button):
            button.setEnabled(connected)

    def set_busy(self, busy):
        for button in (self.sync_button, self.info_button, self.import_button):
            button.setEnabled(not busy)

    def set_logs(self, rows):
        """
        :param rows: Track attribute dicts (log_id, start, activity, category,
            distance_km, duration_s, ascent_m)
        """
        selected = set(self.selected_log_ids())
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for r in rows:
            start = r.get("start")
            item = QTreeWidgetItem(
                [
                    start.toString("yyyy-MM-dd HH:mm")
                    if hasattr(start, "toString")
                    else str(start or ""),
                    r.get("activity") or "",
                    "{:.2f}".format(r.get("distance_km") or 0),
                    _duration(r.get("duration_s")),
                    "{:.0f}".format(r.get("ascent_m") or 0),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, r["log_id"])
            category = r.get("category") or "ground"
            item.setToolTip(1, category_label(category))
            item.setForeground(1, _brush(CATEGORY_COLORS.get(category, "#3584e4")))
            for column in (2, 3, 4):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight)
            self.tree.addTopLevelItem(item)
            if r["log_id"] in selected:
                item.setSelected(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(0, Qt.SortOrder.DescendingOrder)
        for column in range(5):
            self.tree.resizeColumnToContents(column)

    def selected_log_ids(self):
        return [i.data(0, Qt.ItemDataRole.UserRole) for i in self.tree.selectedItems()]


def _brush(color):
    from qgis.PyQt.QtGui import QBrush, QColor

    return QBrush(QColor(color))
