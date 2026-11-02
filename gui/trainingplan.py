"""
MODULE:    qambit.gui.trainingplan
AUTHOR(S): Yann Chemin
PURPOSE:   Edits the training plans of ~/.openambit/training_plans.json (the
           file of openambit2's training plan dialog) and writes one plan to
           the watch.
SPDX-License-Identifier: Unlicense
"""

import copy

from qgis.PyQt.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QDate, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
)

from ..core import plans

STEP_COLUMNS = (
    QT_TRANSLATE_NOOP("QAmbit", "Type"),
    QT_TRANSLATE_NOOP("QAmbit", "Repeat / until"),
    QT_TRANSLATE_NOOP("QAmbit", "Value"),
    QT_TRANSLATE_NOOP("QAmbit", "Unit"),
    QT_TRANSLATE_NOOP("QAmbit", "Target"),
    QT_TRANSLATE_NOOP("QAmbit", "Min"),
    QT_TRANSLATE_NOOP("QAmbit", "Max"),
    QT_TRANSLATE_NOOP("QAmbit", "Beep"),
    QT_TRANSLATE_NOOP("QAmbit", "Light"),
)


def _combo(values, current):
    combo = QComboBox()
    combo.addItems(values)
    combo.setCurrentText(current)
    return combo


def _spin(value, low=0, high=1_000_000):
    spin = QSpinBox()
    spin.setRange(low, high)
    spin.setValue(int(value))
    return spin


class TrainingPlanDialog(QDialog):
    """Emits writeRequested(plan) when the user sends a plan to the watch."""

    writeRequested = pyqtSignal(dict)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Training plans"))
        self.resize(900, 600)
        self.path = path
        self.plans = plans.load_json_list(path) or [plans.new_plan()]
        self.plan_index = -1
        self.entry_index = -1

        self.plan_combo = QComboBox()
        new_plan = QPushButton(self.tr("New plan"))
        rename_plan = QPushButton(self.tr("Rename"))
        delete_plan = QPushButton(self.tr("Delete"))
        top = QHBoxLayout()
        top.addWidget(QLabel(self.tr("Plan:")))
        top.addWidget(self.plan_combo, 1)
        for b in (new_plan, rename_plan, delete_plan):
            top.addWidget(b)

        entries_box = QGroupBox(self.tr("Workouts"))
        self.entries = QTableWidget(0, 2)
        self.entries.setHorizontalHeaderLabels([self.tr("Date"), self.tr("Workout")])
        self.entries.horizontalHeader().setStretchLastSection(True)
        self.entries.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.entries.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        add_entry = QPushButton(self.tr("Add workout"))
        remove_entry = QPushButton(self.tr("Remove workout"))
        el = QVBoxLayout(entries_box)
        el.addWidget(self.entries)
        row = QHBoxLayout()
        row.addWidget(add_entry)
        row.addWidget(remove_entry)
        el.addLayout(row)

        steps_box = QGroupBox(self.tr("Steps of the selected workout"))
        self.steps = QTableWidget(0, len(STEP_COLUMNS))
        self.steps.setHorizontalHeaderLabels(
            [QCoreApplication.translate("QAmbit", c) for c in STEP_COLUMNS]
        )
        self.steps.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        add_step = QPushButton(self.tr("Add step"))
        add_repeat = QPushButton(self.tr("Add repeat"))
        remove_step = QPushButton(self.tr("Remove step"))
        sl = QVBoxLayout(steps_box)
        sl.addWidget(self.steps)
        row = QHBoxLayout()
        for b in (add_step, add_repeat, remove_step):
            row.addWidget(b)
        sl.addLayout(row)

        middle = QHBoxLayout()
        middle.addWidget(entries_box, 1)
        middle.addWidget(steps_box, 3)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        write = box.addButton(
            self.tr("Save && write plan to watch"),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(middle, 1)
        note = QLabel(
            self.tr(
                "The watch runs one plan at a time, as an App Zone app; durations are in "
                "seconds, metres, kcal or bpm."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(box)

        self.plan_combo.currentIndexChanged.connect(self._show_plan)
        new_plan.clicked.connect(self._new_plan)
        rename_plan.clicked.connect(self._rename_plan)
        delete_plan.clicked.connect(self._delete_plan)
        self.entries.currentCellChanged.connect(lambda row, *_: self._show_entry(row))
        add_entry.clicked.connect(self._add_entry)
        remove_entry.clicked.connect(self._remove_entry)
        add_step.clicked.connect(lambda: self._add_step(plans.new_step()))
        add_repeat.clicked.connect(self._add_repeat)
        remove_step.clicked.connect(self._remove_step)
        box.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self._save)
        box.rejected.connect(self.reject)
        write.clicked.connect(self._write)
        self._fill_plans(0)

    # Plans

    def _fill_plans(self, index):
        self.plan_index = -1
        self.plan_combo.blockSignals(True)
        self.plan_combo.clear()
        self.plan_combo.addItems([p.get("name", "") for p in self.plans])
        self.plan_combo.blockSignals(False)
        self.plan_combo.setCurrentIndex(index)
        self._show_plan(index)

    def _plan(self):
        return self.plans[self.plan_index] if 0 <= self.plan_index < len(self.plans) else None

    def _show_plan(self, index):
        self._store()
        self.plan_index = index
        self.entry_index = -1
        plan = self._plan()
        self.entries.blockSignals(True)
        self.entries.setRowCount(0)
        for entry in (plan or {}).get("entries", []):
            self._entry_row(entry)
        self.entries.blockSignals(False)
        self.steps.setRowCount(0)
        if self.entries.rowCount():
            self.entries.selectRow(0)
            self._show_entry(0)

    def _new_plan(self):
        name, ok = QInputDialog.getText(self, self.windowTitle(), self.tr("Plan name:"))
        if ok and name.strip():
            self._store()
            self.plans.append(plans.new_plan(name.strip()))
            self._fill_plans(len(self.plans) - 1)

    def _rename_plan(self):
        plan = self._plan()
        if plan is None:
            return
        name, ok = QInputDialog.getText(
            self,
            self.windowTitle(),
            self.tr("Plan name:"),
            QLineEdit.EchoMode.Normal,
            plan.get("name", ""),
        )
        if ok and name.strip():
            plan["name"] = name.strip()
            self.plan_combo.setItemText(self.plan_index, plan["name"])

    def _delete_plan(self):
        if self._plan() is None:
            return
        self.entry_index = -1
        del self.plans[self.plan_index]
        if not self.plans:
            self.plans.append(plans.new_plan())
        self._fill_plans(0)

    # Workouts

    def _entry_row(self, entry):
        row = self.entries.rowCount()
        self.entries.insertRow(row)
        date = QDateEdit(QDate.fromString(entry.get("date", ""), "yyyy-MM-dd"))
        date.setCalendarPopup(True)
        date.setDisplayFormat("yyyy-MM-dd")
        self.entries.setCellWidget(row, 0, date)
        name = QLineEdit(entry.get("workout", {}).get("name", "Workout"))
        self.entries.setCellWidget(row, 1, name)

    def _show_entry(self, row):
        self._store_steps()
        self.entry_index = row
        self.steps.setRowCount(0)
        plan = self._plan()
        if plan is None or not 0 <= row < len(plan["entries"]):
            return
        for step in plan["entries"][row]["workout"].get("steps", []):
            self._step_row(step)

    def _add_entry(self):
        plan = self._plan()
        if plan is None:
            return
        self._store()
        entry = plans.new_entry(QDate.currentDate().toString("yyyy-MM-dd"))
        plan["entries"].append(entry)
        self._entry_row(entry)
        self.entries.selectRow(self.entries.rowCount() - 1)

    def _remove_entry(self):
        plan = self._plan()
        row = self.entries.currentRow()
        if plan is None or not 0 <= row < len(plan["entries"]):
            return
        self._store_entries()
        self.entry_index = -1
        del plan["entries"][row]
        self._show_plan(self.plan_index)

    # Steps

    def _step_row(self, step):
        row = self.steps.rowCount()
        self.steps.insertRow(row)
        kind = step["type"]["typeName"]
        self.steps.setCellWidget(row, 0, _combo(plans.STEP_TYPES, kind))
        if kind in ("repeatStart", "repeatEnd"):
            if kind == "repeatStart":
                self.steps.setCellWidget(row, 1, _spin(step["type"].get("value", 2), 1, 99))
            return
        duration = step["duration"]
        unit = QLabel(plans.DURATION_UNITS.get(duration["durationName"], ""))
        until = _combo(plans.DURATIONS, duration["durationName"])
        until.currentTextChanged.connect(
            lambda name, label=unit: label.setText(plans.DURATION_UNITS[name])
        )
        self.steps.setCellWidget(row, 1, until)
        self.steps.setCellWidget(row, 2, _spin(duration.get("value", 0)))
        self.steps.setCellWidget(row, 3, unit)
        target = step.get("target", {})
        rng = target.get("valueRange", {})
        self.steps.setCellWidget(row, 4, _combo(plans.TARGETS, target.get("targetName", "none")))
        self.steps.setCellWidget(row, 5, _spin(rng.get("min", 0)))
        self.steps.setCellWidget(row, 6, _spin(rng.get("max", 0)))
        notify = step.get("notify", {})
        for column, key in ((7, "beep"), (8, "light")):
            box = QCheckBox()
            box.setChecked(bool(notify.get(key, True)))
            self.steps.setCellWidget(row, column, box)

    def _read_step(self, row):
        kind = self.steps.cellWidget(row, 0).currentText()
        if kind == "repeatStart":
            count = self.steps.cellWidget(row, 1)
            return {
                "type": {
                    "typeName": kind,
                    "value": count.value() if isinstance(count, QSpinBox) else 2,
                }
            }
        if kind == "repeatEnd":
            return {"type": {"typeName": kind}}
        until = self.steps.cellWidget(row, 1)
        if not isinstance(until, QComboBox):
            # The row was a repeat marker turned into a step.
            return plans.new_step(kind)
        step = plans.new_step(kind, until.currentText(), self.steps.cellWidget(row, 2).value())
        plans.set_target(
            step,
            self.steps.cellWidget(row, 4).currentText(),
            self.steps.cellWidget(row, 5).value(),
            self.steps.cellWidget(row, 6).value(),
        )
        step["notify"] = {
            "beep": self.steps.cellWidget(row, 7).isChecked(),
            "light": self.steps.cellWidget(row, 8).isChecked(),
        }
        return step

    def _add_step(self, step):
        if self.entry_index < 0:
            return
        self._step_row(step)

    def _add_repeat(self):
        start = {"type": {"typeName": "repeatStart", "value": 2}}
        self._add_step(start)
        self._add_step(plans.new_step("interval"))
        self._add_step(plans.new_step("recovery"))
        self._add_step({"type": {"typeName": "repeatEnd"}})

    def _remove_step(self):
        rows = sorted({i.row() for i in self.steps.selectedIndexes()}, reverse=True)
        for row in rows:
            self.steps.removeRow(row)

    # Store and write

    def _store_steps(self):
        plan = self._plan()
        if plan is None or not 0 <= self.entry_index < len(plan["entries"]):
            return
        steps = [self._read_step(r) for r in range(self.steps.rowCount())]
        plan["entries"][self.entry_index]["workout"]["steps"] = steps

    def _store_entries(self):
        plan = self._plan()
        if plan is None:
            return
        for row, entry in enumerate(plan["entries"]):
            if row >= self.entries.rowCount():
                break
            entry["date"] = self.entries.cellWidget(row, 0).date().toString("yyyy-MM-dd")
            entry["workout"]["name"] = self.entries.cellWidget(row, 1).text() or "Workout"

    def _store(self):
        self._store_steps()
        self._store_entries()

    def _save(self):
        self._store()
        try:
            plans.save_json(self.path, self.plans)
        except OSError as e:
            QMessageBox.critical(self, self.windowTitle(), str(e))
            return False
        return True

    def _write(self):
        self._store()
        plan = self._plan()
        if plan is None:
            return
        problems = plans.check_plan(plan)
        if problems:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(problems))
            return
        if self._save():
            self.writeRequested.emit(copy.deepcopy(plan))
            self.accept()
