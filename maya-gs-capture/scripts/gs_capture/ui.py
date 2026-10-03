"""Small Maya-native workflow; no server, training process, or external Qt install."""
import copy
import json
import traceback
from pathlib import Path

import maya.cmds as cmds
import maya.OpenMayaUI as omui
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid, wrapInstance

from . import dataset, maya_scene, render

_window = None


class CapturePanel(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GSCapturePanel")
        self.setWindowTitle("Render for 4DGS")
        self.resize(720, 700)
        self.targets = []
        self.session = None
        self.pending = []
        self.cancel_requested = False
        self.running = False
        self.build_ui()
        self.load_preferences()

    def build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("Render for 4DGS")
        title.setStyleSheet("font-size: 23px; font-weight: 600; padding: 8px 0;")
        outer.addWidget(title)
        self.controls = QtWidgets.QWidget()
        outer.addWidget(self.controls)
        layout = QtWidgets.QVBoxLayout(self.controls)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QtWidgets.QGroupBox("Frame and Timeline")
        form = QtWidgets.QFormLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.target_label = QtWidgets.QLabel("No effect objects selected")
        self.target_label.setWordWrap(True)
        row.addWidget(self.target_label, 1)
        choose = QtWidgets.QPushButton("Use Selection")
        choose.clicked.connect(lambda: self.guard(self.choose_targets))
        row.addWidget(choose)
        form.addRow("Framing targets", row)
        self.start = self.spin(-100000, 100000, int(cmds.playbackOptions(query=True, min=True)))
        self.end = self.spin(-100000, 100000, int(cmds.playbackOptions(query=True, max=True)))
        self.step = self.spin(1, 10000, 1)
        frames = QtWidgets.QHBoxLayout()
        for label, widget in (("Start", self.start), ("End", self.end), ("Step", self.step)):
            frames.addWidget(QtWidgets.QLabel(label))
            frames.addWidget(widget)
            widget.valueChanged.connect(self.update_count)
        self.timeline_button = QtWidgets.QPushButton("Use Current Timeline")
        self.timeline_button.clicked.connect(lambda: self.guard(self.use_current_timeline))
        frames.addWidget(self.timeline_button)
        form.addRow("Frame range", frames)
        self.count = QtWidgets.QLabel()
        form.addRow("Image count", self.count)
        self.cached = QtWidgets.QCheckBox("Simulation is cached and supports arbitrary frame access")
        form.addRow(self.cached)
        self.cached.setToolTip("When resuming, external caches, textures, HDRIs, and light assets must be unchanged.")
        layout.addWidget(box)

        box = QtWidgets.QGroupBox("Cameras")
        form = QtWidgets.QFormLayout(box)
        self.focal = self.double_spin(10, 150, 35)
        self.margin = self.double_spin(1.01, 5, 1.15)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Focal length (mm)")); row.addWidget(self.focal)
        row.addWidget(QtWidgets.QLabel("Distance scale")); row.addWidget(self.margin)
        form.addRow(row)
        self.low = self.double_spin(-70, 75, 10)
        self.high = self.double_spin(-70, 80, 45)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Lower elevation (°)")); row.addWidget(self.low)
        row.addWidget(QtWidgets.QLabel("Upper elevation (°)")); row.addWidget(self.high)
        form.addRow(row)
        create = QtWidgets.QPushButton("Scan Animation Bounds and Create 16 Cameras")
        create.clicked.connect(lambda: self.guard(self.create_rig))
        form.addRow(create)
        self.holdout = QtWidgets.QLineEdit("CAM004, CAM012")
        form.addRow("Validation cameras", self.holdout)
        layout.addWidget(box)

        box = QtWidgets.QGroupBox("Output")
        form = QtWidgets.QFormLayout(box)
        self.output = QtWidgets.QLineEdit()
        self.output.setPlaceholderText("An empty folder, or the previous folder for this exact capture")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self.choose_output)
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.output, 1); row.addWidget(browse)
        form.addRow("Output folder", row)
        self.revision = QtWidgets.QLineEdit("v001")
        form.addRow("Asset revision", self.revision)
        self.device = QtWidgets.QComboBox(); self.device.addItems(["CPU (compatibility)", "GPU (current Arnold GPU settings)"])
        self.aa = self.spin(1, 10, 3)
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.device, 1); row.addWidget(QtWidgets.QLabel("AA")); row.addWidget(self.aa)
        form.addRow("Renderer", row)
        layout.addWidget(box)
        actions = QtWidgets.QHBoxLayout()
        for text, callback in (("Validate", self.check), ("Preview 3 Images", lambda: self.start_render(True)),
                               ("Render", lambda: self.start_render(False))):
            button = QtWidgets.QPushButton(text)
            button.setMinimumHeight(34)
            button.clicked.connect(lambda checked=False, fn=callback: self.guard(fn))
            actions.addWidget(button)
        layout.addLayout(actions)
        workbench = QtWidgets.QPushButton("Open Training Workbench")
        workbench.clicked.connect(lambda: self.guard(self.open_workbench))
        layout.addWidget(workbench)
        self.progress = QtWidgets.QProgressBar(); outer.addWidget(self.progress)
        row = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Ready")
        self.status.setWordWrap(True)
        self.stop_button = QtWidgets.QPushButton("Stop After Current Image")
        self.stop_button.setEnabled(False); self.stop_button.clicked.connect(self.request_cancel)
        row.addWidget(self.status, 1); row.addWidget(self.stop_button); outer.addLayout(row)
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(1000)
        self.log.setMinimumHeight(90); outer.addWidget(self.log, 1)
        self.update_count()

    @staticmethod
    def spin(low, high, value):
        widget = QtWidgets.QSpinBox(); widget.setRange(low, high); widget.setValue(value)
        return widget

    @staticmethod
    def double_spin(low, high, value):
        widget = QtWidgets.QDoubleSpinBox(); widget.setRange(low, high); widget.setValue(value)
        widget.setDecimals(2)
        return widget

    def guard(self, action):
        try:
            action()
        except Exception as exc:
            self.log.appendPlainText(str(exc))
            traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "Render for 4DGS", str(exc))

    def choose_targets(self):
        self.targets = maya_scene.selected_targets()
        self.target_label.setText(", ".join(x.split("|")[-1] for x in self.targets))

    def choose_output(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Capture Folder", self.output.text(),
            options=QtWidgets.QFileDialog.Option.ShowDirsOnly | QtWidgets.QFileDialog.Option.DontUseNativeDialog)
        if directory:
            self.output.setText(directory)

    def use_current_timeline(self):
        self.start.setValue(int(cmds.playbackOptions(query=True, min=True)))
        self.end.setValue(int(cmds.playbackOptions(query=True, max=True)))
        self.update_count()

    def update_count(self):
        try:
            count = len(dataset.frames_for(self.start.value(), self.end.value(), self.step.value()))
            self.count.setText(f"{count * 16:,} PNG images")
        except ValueError as exc:
            self.count.setText(str(exc))

    def settings(self):
        if not self.cached.isChecked():
            raise ValueError("Cache the simulation first, then confirm arbitrary frame access and unchanged external assets.")
        if not self.targets:
            raise ValueError("Choose the framing targets first.")
        holdout = [x.strip() for x in self.holdout.text().replace("\uff0c", ",").split(",") if x.strip()]
        if len(holdout) != 2 or len(set(holdout)) != 2:
            raise ValueError("Enter two different validation camera IDs, for example: CAM004, CAM012.")
        return dict(start=self.start.value(), end=self.end.value(), step=self.step.value(),
                    aa_samples=self.aa.value(), device=self.device.currentIndex(),
                    test_cameras=holdout, asset_revision=self.revision.text().strip(),
                    output_color="Current Maya view transform; straight RGBA PNG8")

    def with_scan(self, title, action):
        dialog = QtWidgets.QProgressDialog(title, "Cancel", 0, 100, self)
        dialog.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0)
        def progress(current, total):
            dialog.setValue(int(100 * current / total))
            # Restrict user interaction to cancellation while Maya evaluates cached frames.
            QtWidgets.QApplication.processEvents()
            return not dialog.wasCanceled()
        try:
            return action(progress)
        finally:
            dialog.close()

    def create_rig(self):
        settings = self.settings()
        if cmds.objExists(maya_scene.RIG):
            raise ValueError("GS_CameraRig already exists. Adjust it manually, or delete the old rig before rebuilding.")
        bounds = self.with_scan("Scanning all sampled frames…", lambda progress: maya_scene.scan_bounds(
            self.targets, dataset.frames_for(settings["start"], settings["end"], settings["step"]), progress))
        maya_scene.create_rig(bounds, self.focal.value(), self.margin.value(),
                              (self.low.value(), self.high.value()))
        self.log.appendPlainText("Created 16 cameras. Check framing, save the scene with Ctrl+S, then render a preview.")
        self.save_preferences()

    def get_plan(self):
        settings = self.settings()
        render.ensure_arnold()
        plan = self.with_scan("Validating cameras and animation bounds…", lambda progress:
            maya_scene.collect_plan(settings, self.targets, progress))
        self.save_preferences()
        return plan

    def check(self):
        plan = self.get_plan()
        self.log.appendPlainText(f"Validation passed: {len(plan['records'])} images; {plan['source']['fps']:g} FPS; "
                                 f"horizontal FOV {plan['camera_angle_x'] * 180 / 3.14159265:.2f}°.\n"
                                 "Preview framing, lighting, cache consistency, and transparency before exporting.")

    def start_render(self, preview):
        if not self.output.text().strip():
            raise ValueError("Choose an output folder.")
        plan = self.get_plan()
        root = Path(self.output.text().strip()).expanduser().resolve()
        if preview:
            records = plan["records"]
            count = len(records) // 16
            selected = [records[0], records[(count // 2) * 16 + 8], records[(count - 1) * 16 + 4]]
            plan = copy.deepcopy(plan)
            plan["records"] = selected
            plan["preview"] = True
            plan["fingerprint"] = dataset.fingerprint({k: v for k, v in plan.items() if k != "fingerprint"})
            # Preview beside the main dataset: a preview never makes the dataset directory nonempty.
            root = root.parent / (root.name + "_preview_" + plan["fingerprint"][:10])
        self.session = dataset.OutputSession(root, plan, preview)
        self.pending = list(plan["records"])
        self.total = len(self.pending)
        self.finished = 0
        self.cancel_requested = False
        self.running = True
        self.controls.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.hide()
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.show()
        self.progress.setRange(0, self.total); self.progress.setValue(0)
        self.log.appendPlainText("Starting preview: " + str(root) if preview else "Starting export: " + str(root))
        self.log.appendPlainText("Do not edit the scene while rendering. Click Stop, or press Esc during a Maya render.")
        QtCore.QTimer.singleShot(50, self.next_image)

    def next_image(self):
        try:
            if self.cancel_requested:
                self.session.stop()
                self.end_job("Stopped. Resume with the same scene and settings.")
                return
            if not self.pending:
                self.session.finish()
                self.end_job("Preview complete" if self.session.preview else "Export complete. Dataset ready for training.")
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.session.root)))
                return
            record = self.pending.pop(0)
            self.status.setText(f"{record['camera']} · Maya frame {record['maya_frame']} · {self.finished + 1}/{self.total}")
            if not self.session.done(record):
                render.render_one(self.session, record)
            self.finished += 1
            self.progress.setValue(self.finished)
            QtCore.QTimer.singleShot(50, self.next_image)
        except Exception as exc:
            traceback.print_exc()
            try:
                self.session.stop(exc)
            finally:
                self.end_job("Render stopped: " + str(exc))

    def request_cancel(self):
        self.cancel_requested = True
        self.stop_button.setEnabled(False)
        self.status.setText("Waiting for the current Arnold render…")

    def open_workbench(self):
        import os
        import subprocess
        project = Path(__file__).resolve().parents[3]
        python = project / ".envs/workbench/Scripts/pythonw.exe"
        entry = project / "workbench/main.py"
        if not python.is_file() or not entry.is_file():
            raise ValueError("The training workbench is not installed next to this plugin.")
        folder = Path(self.output.text().strip()).expanduser().resolve()
        manifest = folder / "capture_manifest.json"
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("status") != "complete":
            raise ValueError("Finish the full dataset export before opening it in the training workbench.")
        environment = dict(os.environ)
        # Maya's embedded Python and Qt search paths must not leak into the desktop process.
        for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                     "QML2_IMPORT_PATH", "QML_IMPORT_PATH", "QT_QPA_PLATFORM"):
            environment.pop(name, None)
        subprocess.Popen([str(python), str(entry), "--dataset", str(folder)], cwd=str(project),
                         env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        self.log.appendPlainText("Capture sent to the training workbench.")

    def end_job(self, message):
        self.running = False
        self.controls.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.hide()
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self.show()
        self.status.setText(message)
        self.log.appendPlainText(message)

    def save_preferences(self):
        value = dict(output=self.output.text(), revision=self.revision.text(),
                     start=self.start.value(), end=self.end.value(), step=self.step.value(),
                     aa=self.aa.value(), device=self.device.currentIndex(), holdout=self.holdout.text(),
                     focal=self.focal.value(), margin=self.margin.value(), low=self.low.value(), high=self.high.value())
        cmds.optionVar(stringValue=("gsCapturePreferences", json.dumps(value)))

    def load_preferences(self):
        if not cmds.optionVar(exists="gsCapturePreferences"):
            return
        try:
            data = json.loads(cmds.optionVar(query="gsCapturePreferences"))
            for name in ("output", "revision", "holdout"):
                getattr(self, name).setText(data[name])
            for name in ("start", "end", "step", "aa", "focal", "margin", "low", "high"):
                getattr(self, name).setValue(data[name])
            self.device.setCurrentIndex(data["device"])
        except (KeyError, ValueError, TypeError):
            pass

    def closeEvent(self, event):
        if self.running:
            self.request_cancel()
            event.ignore()
        else:
            self.save_preferences()
            event.accept()


def show():
    global _window
    if _window is None or not isValid(_window):
        pointer = omui.MQtUtil.mainWindow()
        parent = wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None
        _window = CapturePanel(parent)
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window
