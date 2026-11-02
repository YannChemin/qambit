"""
MODULE:    qambit.gui.sportmodes
AUTHOR(S): Yann Chemin
PURPOSE:   Edits the sport modes of ~/.openambit/sport_modes.json (the file
           the openambit2 editor uses) and writes them to the watch.
SPDX-License-Identifier: Unlicense
"""

import copy

from qgis.PyQt.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core import activity, plans

GPS_INTERVALS = (
    (0, QT_TRANSLATE_NOOP("QAmbit", "Best")),
    (1, QT_TRANSLATE_NOOP("QAmbit", "1 s")),
    (2, QT_TRANSLATE_NOOP("QAmbit", "2 s")),
    (5, QT_TRANSLATE_NOOP("QAmbit", "5 s")),
    (10, QT_TRANSLATE_NOOP("QAmbit", "10 s")),
    (15, QT_TRANSLATE_NOOP("QAmbit", "15 s")),
    (30, QT_TRANSLATE_NOOP("QAmbit", "30 s")),
    (60, QT_TRANSLATE_NOOP("QAmbit", "60 s")),
)
RECORDING_INTERVALS = (
    (1, QT_TRANSLATE_NOOP("QAmbit", "1 s")),
    (5, QT_TRANSLATE_NOOP("QAmbit", "5 s")),
    (10, QT_TRANSLATE_NOOP("QAmbit", "10 s")),
    (60, QT_TRANSLATE_NOOP("QAmbit", "60 s")),
)
CHECKS = (
    ("UseHRBelt", QT_TRANSLATE_NOOP("QAmbit", "HR belt")),
    ("UseFootPOD", QT_TRANSLATE_NOOP("QAmbit", "Foot pod")),
    ("UseBikePOD", QT_TRANSLATE_NOOP("QAmbit", "Bike pod")),
    ("UseCadencePOD", QT_TRANSLATE_NOOP("QAmbit", "Cadence pod")),
    ("UseAccelerometer", QT_TRANSLATE_NOOP("QAmbit", "Accelerometer")),
)
ALTI_MODES = (
    (0, QT_TRANSLATE_NOOP("QAmbit", "Off")),
    (1, QT_TRANSLATE_NOOP("QAmbit", "Altitude")),
    (2, QT_TRANSLATE_NOOP("QAmbit", "Barometer")),
)
BACKLIGHT_MODES = (
    (0, QT_TRANSLATE_NOOP("QAmbit", "Auto off")),
    (1, QT_TRANSLATE_NOOP("QAmbit", "Always on")),
    (2, QT_TRANSLATE_NOOP("QAmbit", "Invert")),
)
# The air sports templates of core.activity, named for the translation tools.
PRESET_NAMES = (
    QT_TRANSLATE_NOOP("QAmbit", "Paragliding"),
    QT_TRANSLATE_NOOP("QAmbit", "Hang Gliding"),
    QT_TRANSLATE_NOOP("QAmbit", "Speed Flying"),
    QT_TRANSLATE_NOOP("QAmbit", "Paramotor"),
    QT_TRANSLATE_NOOP("QAmbit", "Gliding"),
    QT_TRANSLATE_NOOP("QAmbit", "Microlight ULM"),
    QT_TRANSLATE_NOOP("QAmbit", "Gyrocopter"),
    QT_TRANSLATE_NOOP("QAmbit", "Powered Flight"),
    QT_TRANSLATE_NOOP("QAmbit", "Helicopter"),
    QT_TRANSLATE_NOOP("QAmbit", "Balloon"),
    QT_TRANSLATE_NOOP("QAmbit", "Skydiving"),
    QT_TRANSLATE_NOOP("QAmbit", "Wingsuit"),
)


def _t(text):
    return QCoreApplication.translate("QAmbit", text)


def _combo(items):
    combo = QComboBox()
    for value, label in items:
        combo.addItem(_t(label), value)
    return combo


def _select(combo, value):
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


class SportModesDialog(QDialog):
    """Emits writeRequested(modes) when the user sends the modes to the watch."""

    writeRequested = pyqtSignal(list)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Sport modes"))
        self.path = path
        self.modes = plans.load_json_list(path)
        self.current = -1

        self.list = QListWidget()
        add = QPushButton(self.tr("Add"))
        menu = QMenu(add)
        menu.addAction(self.tr("Blank sport mode"), self._add_blank)
        air = menu.addMenu(self.tr("Air sports"))
        for name, activity_id, gps, rec in activity.AIR_SPORT_PRESETS:
            label = _t(name)
            air.addAction(
                label,
                lambda _=False, n=label, a=activity_id, g=gps, r=rec: self._add(n, a, g, r, 1),
            )
        add.setMenu(menu)
        self.remove = QPushButton(self.tr("Remove"))
        self.up = QPushButton(self.tr("Up"))
        self.down = QPushButton(self.tr("Down"))
        buttons = QHBoxLayout()
        for b in (add, self.remove, self.up, self.down):
            buttons.addWidget(b)
        left = QVBoxLayout()
        left.addWidget(self.list)
        left.addLayout(buttons)
        self.count = QLabel()
        left.addWidget(self.count)

        self.form = QWidget()
        form = QFormLayout(self.form)
        self.name = QLineEdit()
        self.name.setMaxLength(activity.WATCH_NAME_LENGTH)
        self.activity = QComboBox()
        for activity_id, name in sorted(activity.ACTIVITY_NAMES.items(), key=lambda i: i[1]):
            self.activity.addItem("{} ({})".format(name, activity_id), activity_id)
        self.gps = _combo(GPS_INTERVALS)
        self.recording = _combo(RECORDING_INTERVALS)
        self.alti = _combo(ALTI_MODES)
        self.checks = {key: QCheckBox(_t(label)) for key, label in CHECKS}
        self.hr_limits = QCheckBox(self.tr("Use HR limits"))
        self.hr_low = QSpinBox()
        self.hr_high = QSpinBox()
        for box in (self.hr_low, self.hr_high):
            box.setRange(30, 220)
            box.setSuffix(" bpm")
        self.autolap = QCheckBox(self.tr("Use autolap"))
        self.autolap_m = QSpinBox()
        self.autolap_m.setRange(0, 100000)
        self.autolap_m.setSuffix(" m")
        self.autopause = QDoubleSpinBox()
        self.autopause.setRange(0.0, 10.0)
        self.autopause.setSingleStep(0.1)
        self.autopause.setSuffix(self.tr(" m/s (0 = off)"))
        self.backlight = _combo(BACKLIGHT_MODES)
        self.negative = QCheckBox(self.tr("Negative display"))

        form.addRow(self.tr("Name:"), self.name)
        form.addRow(self.tr("Activity:"), self.activity)
        form.addRow(self.tr("GPS interval:"), self.gps)
        form.addRow(self.tr("Recording interval:"), self.recording)
        form.addRow(self.tr("Alti/baro mode:"), self.alti)
        for box in self.checks.values():
            form.addRow("", box)
        form.addRow(self.hr_limits)
        form.addRow(self.tr("HR low:"), self.hr_low)
        form.addRow(self.tr("HR high:"), self.hr_high)
        form.addRow(self.autolap, self.autolap_m)
        form.addRow(self.tr("Auto pause:"), self.autopause)
        form.addRow(self.tr("Backlight:"), self.backlight)
        form.addRow("", self.negative)
        hint = QLabel(
            self.tr("Air sports: altitude mode, so that climbs are not read as weather changes.")
        )
        hint.setWordWrap(True)
        form.addRow(hint)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addWidget(self.form, 2)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        self.write_button = box.addButton(
            self.tr("Save && write to watch"), QDialogButtonBox.ButtonRole.ActionRole
        )
        layout = QVBoxLayout(self)
        layout.addLayout(body)
        layout.addWidget(box)

        self.list.currentRowChanged.connect(self._show)
        self.remove.clicked.connect(self._remove)
        self.up.clicked.connect(lambda: self._move(-1))
        self.down.clicked.connect(lambda: self._move(1))
        box.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self._save)
        box.rejected.connect(self.reject)
        self.write_button.clicked.connect(self._write)
        self.name.textEdited.connect(self._rename)
        self._refresh()

    def _refresh(self, row=0):
        self.list.clear()
        for mode in self.modes:
            self.list.addItem(mode.get("Name") or self.tr("(unnamed)"))
        n = len(self.modes)
        self.count.setText(self.tr("{} of {} sport modes").format(n, plans.MAX_SPORT_MODES))
        style = "color: #c01c28" if n > plans.MAX_SPORT_MODES else ""
        self.count.setStyleSheet(style)
        self.current = -1
        if n:
            self.list.setCurrentRow(max(0, min(row, n - 1)))
        self.form.setEnabled(n > 0)

    def _store(self):
        """Copies the form into the mode being edited."""
        if not 0 <= self.current < len(self.modes):
            return
        m = self.modes[self.current]
        m["Name"] = self.name.text()
        m["ActivityID"] = self.activity.currentData()
        m["GPSInterval"] = self.gps.currentData()
        m["RecordingInterval"] = self.recording.currentData()
        m["AltiBaroMode"] = self.alti.currentData()
        for key, box in self.checks.items():
            m[key] = box.isChecked()
        m["UseHRLimits"] = self.hr_limits.isChecked()
        m["HRLimitLow"] = self.hr_low.value()
        m["HRLimitHigh"] = self.hr_high.value()
        m["UseAutolap"] = self.autolap.isChecked()
        m["AutolapDistance"] = self.autolap_m.value()
        m["AutoPauseSpeed"] = self.autopause.value()
        m["BacklightMode"] = self.backlight.currentData()
        m["DisplayIsNegative"] = 1 if self.negative.isChecked() else 0

    def _show(self, row):
        self._store()
        self.current = row
        if not 0 <= row < len(self.modes):
            return
        m = self.modes[row]
        self.name.setText(m.get("Name", ""))
        activity_id = m.get("ActivityID", activity.ACTIVITY_UNSPECIFIED)
        if self.activity.findData(activity_id) < 0:
            self.activity.addItem(activity.activity_name(activity_id), activity_id)
        _select(self.activity, activity_id)
        _select(self.gps, m.get("GPSInterval", 1))
        _select(self.recording, m.get("RecordingInterval", 1))
        _select(self.alti, m.get("AltiBaroMode", 0))
        for key, box in self.checks.items():
            box.setChecked(bool(m.get(key, False)))
        self.hr_limits.setChecked(bool(m.get("UseHRLimits", False)))
        self.hr_low.setValue(int(m.get("HRLimitLow", 120)))
        self.hr_high.setValue(int(m.get("HRLimitHigh", 180)))
        self.autolap.setChecked(bool(m.get("UseAutolap", False)))
        self.autolap_m.setValue(int(m.get("AutolapDistance", 0)))
        self.autopause.setValue(float(m.get("AutoPauseSpeed", 0.0)))
        _select(self.backlight, m.get("BacklightMode", 0))
        self.negative.setChecked(bool(m.get("DisplayIsNegative", 0)))

    def _rename(self, text):
        item = self.list.currentItem()
        if item is not None:
            item.setText(text or self.tr("(unnamed)"))

    def _add(self, name, activity_id, gps=1, recording=1, alti=0):
        self._store()
        plans.add_mode(self.modes, name, activity_id, gps, recording, alti)
        self._refresh(len(self.modes) - 1)

    def _add_blank(self):
        self._add(self.tr("New mode"), activity.ACTIVITY_UNSPECIFIED)

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.modes):
            self.current = -1
            del self.modes[row]
            self._refresh(row)

    def _move(self, step):
        self._store()
        row = self.list.currentRow()
        other = row + step
        if 0 <= row < len(self.modes) and 0 <= other < len(self.modes):
            self.modes[row], self.modes[other] = self.modes[other], self.modes[row]
            self.current = -1
            self._refresh(other)

    def _save(self):
        self._store()
        try:
            plans.save_json(self.path, self.modes)
        except OSError as e:
            QMessageBox.critical(self, self.windowTitle(), str(e))
            return False
        return True

    def _write(self):
        self._store()
        problems = plans.check_sport_modes(self.modes)
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        if self._save():
            self.writeRequested.emit(copy.deepcopy(self.modes))
            self.accept()
