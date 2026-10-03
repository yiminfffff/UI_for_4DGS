"""English-only Houdini capture panel with an isolated background renderer."""
from functools import wraps
import json
import os
from pathlib import Path
import subprocess
import traceback
import uuid

import hou
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid

from . import dataset, scene

_window = None


def action(method):
    @wraps(method)
    def guarded(self, *args):
        try:
            return method(self)
        except Exception as exc:
            traceback.print_exc()
            self.status.setText(str(exc))
            self.log.appendPlainText("Error: " + str(exc))
            QtWidgets.QMessageBox.warning(self, "Render for 4DGS", str(exc))
    return guarded


class CapturePanel(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Render for 4DGS")
        self.setObjectName("GS_CAPTURE_HOUDINI")
        self.resize(760, 900)
        self.process = None
        self.stop_file = None
        self.output_buffer = ""
        self.terminal_event = False
        self.preferences = Path(hou.getenv("HOUDINI_USER_PREF_DIR")) / "gs_capture_preferences.json"
        self.setStyleSheet("QPushButton {min-height:25px; padding:2px 10px;} "
                           "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {min-height:25px;}")
        layout = QtWidgets.QVBoxLayout(self)
        self.controls = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(self.controls)
        body.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.controls)

        group, form = self.group("Frame and Timeline")
        self.source = QtWidgets.QLineEdit()
        self.source.setPlaceholderText("/stage/OUT_EFFECT")
        form.addRow("Source LOP", self.row(self.source, self.button("Use Selection", self.use_source)))
        self.targets = QtWidgets.QLineEdit()
        self.targets.setPlaceholderText("/World/Effect")
        form.addRow("Framing Primitives", self.row(self.targets, self.button("Use Selection", self.use_targets)))
        self.start = self.integer(-100000, 100000, 1)
        self.end = self.integer(-100000, 100000, 120)
        self.step = self.integer(1, 10000, 1)
        form.addRow("Frame Range", self.row(self.start, QtWidgets.QLabel("to"), self.end,
                    QtWidgets.QLabel("Step"), self.step, self.button("Use Current Timeline", self.use_timeline)))
        self.count = QtWidgets.QLabel()
        form.addRow("Image Count", self.count)
        self.cached = QtWidgets.QCheckBox("Simulation is cached for every sampled frame")
        form.addRow(self.cached)
        body.addWidget(group)

        group, form = self.group("Cameras")
        self.focal = self.decimal(10, 200, 35)
        self.margin = self.decimal(1, 3, 1.15)
        form.addRow("Framing", self.row(QtWidgets.QLabel("Focal Length"), self.focal,
                     QtWidgets.QLabel("mm"), QtWidgets.QLabel("Margin"), self.margin))
        self.low = self.decimal(-80, 80, 10)
        self.high = self.decimal(-80, 80, 45)
        form.addRow("Ring Elevation", self.row(self.low, QtWidgets.QLabel("deg"), self.high, QtWidgets.QLabel("deg")))
        self.holdout = QtWidgets.QLineEdit("CAM004, CAM012")
        form.addRow("Validation Cameras", self.holdout)
        form.addRow(self.row(self.button("Scan and Create 16 Cameras", self.create_cameras),
                            self.button("Validate Scene", self.validate_scene)))
        body.addWidget(group)

        group, form = self.group("Output")
        self.output = QtWidgets.QLineEdit()
        self.output.setPlaceholderText("Choose an empty dataset folder")
        form.addRow("Dataset Folder", self.row(self.output, self.button("Browse", self.browse)))
        self.revision = QtWidgets.QLineEdit("v1")
        form.addRow("Asset Revision", self.revision)
        self.engine = QtWidgets.QComboBox()
        self.engine.addItem("Karma CPU", "cpu")
        self.engine.addItem("Karma XPU", "xpu")
        self.samples = self.integer(1, 4096, 128)
        form.addRow("Renderer", self.row(self.engine, QtWidgets.QLabel("Samples"), self.samples))
        self.display = QtWidgets.QComboBox()
        self.view = QtWidgets.QComboBox()
        _, config = scene.color_config()
        self.display.addItems(list(config.getDisplays()))
        self.display.currentTextChanged.connect(self.update_views)
        self.update_views()
        self.display.setCurrentText("sRGB - Display")
        self.view.setCurrentText("ACES 1.0 - SDR Video")
        form.addRow("Color Display / View", self.row(self.display, self.view))
        form.addRow(self.row(self.button("Render 3 Previews", self.preview), self.button("Render", self.render)))
        form.addRow(self.row(self.button("Open Output", self.open_output),
                            self.button("Open Training Workbench", self.open_workbench)))
        body.addWidget(group)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QtWidgets.QLabel("Ready")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.stop_button = self.button("Stop After Current Image", self.request_stop)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMinimumHeight(90)
        layout.addWidget(self.log, 1)
        for widget in (self.start, self.end, self.step):
            widget.valueChanged.connect(self.update_count)
        self.use_timeline()
        self.load_preferences()
        self.update_count()

    @staticmethod
    def group(title):
        group = QtWidgets.QFrame()
        group.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        layout = QtWidgets.QVBoxLayout(group)
        header = QtWidgets.QLabel(title)
        font = header.font()
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)
        form = QtWidgets.QFormLayout()
        form.setVerticalSpacing(7)
        layout.addLayout(form)
        return group, form

    @staticmethod
    def row(*widgets):
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            layout.addWidget(widget)
        return row

    @staticmethod
    def button(label, callback):
        button = QtWidgets.QPushButton(label)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def integer(low, high, value):
        widget = QtWidgets.QSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        return widget

    @staticmethod
    def decimal(low, high, value):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        return widget

    def update_views(self, *args):
        old = self.view.currentText()
        _, config = scene.color_config()
        self.view.clear()
        self.view.addItems(list(config.getViews(self.display.currentText())))
        if self.view.findText(old) >= 0:
            self.view.setCurrentText(old)

    def update_count(self, *args):
        try:
            count = 16 * len(dataset.frames_for(self.start.value(), self.end.value(), self.step.value()))
            self.count.setText(f"{count:,} PNG images")
        except ValueError:
            self.count.setText("Invalid frame range")

    @action
    def use_source(self):
        self.source.setText(scene.selected_source())

    @action
    def use_targets(self):
        self.targets.setText(", ".join(scene.selected_prims()))

    def use_timeline(self, *args):
        start, end = hou.playbar.playbackRange()
        self.start.setValue(round(start))
        self.end.setValue(round(end))

    def settings(self):
        if not self.cached.isChecked():
            raise ValueError("Cache the simulation first, then enable the cached simulation checkbox.")
        revision = self.revision.text().strip()
        if not revision:
            raise ValueError("Enter an asset revision. Change it whenever external caches, textures, or lights change.")
        return dict(start=self.start.value(), end=self.end.value(), step=self.step.value(),
                    test_cameras=self.holdout.text().replace(",", " ").split(),
                    engine=self.engine.currentData(), samples=self.samples.value(), asset_revision=revision,
                    display=self.display.currentText(), view=self.view.currentText())

    def with_progress(self, title, operation):
        progress = QtWidgets.QProgressDialog(title, "Cancel", 0, 100, self)
        progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        self.controls.setEnabled(False)
        def update(current, total):
            progress.setValue(round(100 * current / total))
            QtWidgets.QApplication.processEvents()
            return not progress.wasCanceled()
        try:
            return operation(update)
        finally:
            progress.close()
            self.controls.setEnabled(True)

    @action
    def create_cameras(self):
        settings = self.settings()
        node = scene.source_node(self.source.text().strip())
        targets = scene.target_paths(self.targets.text())
        frames = dataset.frames_for(settings["start"], settings["end"], settings["step"])
        bounds = self.with_progress("Scanning animation bounds...",
                    lambda callback: scene.scan_bounds(node, targets, frames, callback))
        rig = scene.create_rig(node, bounds, self.focal.value(), self.margin.value(),
                               (self.low.value(), self.high.value()))
        self.status.setText("16 cameras created. Save the HIP file before rendering.")
        self.log.appendPlainText("Camera rig: " + rig.path())

    def plan(self):
        settings = self.settings()
        return self.with_progress("Validating cameras and animation bounds...",
            lambda callback: scene.collect_plan(settings, self.source.text().strip(),
                scene.target_paths(self.targets.text()), callback))

    @action
    def validate_scene(self):
        plan = self.plan()
        self.status.setText(f"Validation passed. {len(plan['records']):,} PNG images ready to render.")
        self.log.appendPlainText(self.status.text())

    @action
    def browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Dataset Folder", self.output.text())
        if folder:
            self.output.setText(folder)

    @action
    def preview(self):
        self.start_job(True)

    @action
    def render(self):
        self.start_job(False)

    def start_job(self, preview):
        if self.process is not None:
            raise RuntimeError("A render is already running.")
        if not self.output.text().strip():
            raise ValueError("Choose an output folder first.")
        output = Path(self.output.text().strip()).expanduser().resolve()
        if preview:
            output = output.with_name(output.name + "_preview")
        plan = self.plan()
        jobs = self.preferences.parent / "gs_capture_jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        self.stop_file = jobs / (identifier + ".stop")
        self.job_file = jobs / (identifier + ".json")
        dataset.write_json(self.job_file, dict(plan=plan, output=str(output), preview=preview,
                                             stop_file=str(self.stop_file)))
        self.save_preferences()
        self.terminal_event = False
        self.output_buffer = ""
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        environment = QtCore.QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.controls.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress.setRange(0, 3 if preview else len(plan["records"]))
        self.progress.setValue(0)
        self.status.setText("Starting Karma in the background...")
        self.log.appendPlainText("Output: " + str(output))
        executable = str(Path(hou.getenv("HFS")) / "bin/hython.exe")
        self.process.start(executable, [str(Path(__file__).with_name("worker.py")), "--job", str(self.job_file)])

    def read_output(self):
        self.output_buffer += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.output_buffer:
            line, self.output_buffer = self.output_buffer.split("\n", 1)
            line = line.rstrip()
            if "@GSC@" not in line:
                if line:
                    self.log.appendPlainText(line)
                continue
            try:
                event = json.loads(line.split("@GSC@", 1)[1])
            except ValueError:
                self.log.appendPlainText(line)
                continue
            kind = event["event"]
            if kind == "progress":
                self.progress.setRange(0, event["total"])
                self.progress.setValue(event["completed"])
            elif kind == "complete":
                self.terminal_event = True
                self.status.setText("Preview complete." if event["preview"] else "Dataset complete. Ready for training.")
                self.log.appendPlainText(self.status.text() + " " + event["output"])
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(event["output"]))
            else:
                self.status.setText(event.get("message", ""))
                self.log.appendPlainText(self.status.text())
                if kind in ("error", "cancelled"):
                    self.terminal_event = True

    def process_error(self, error):
        if error == QtCore.QProcess.ProcessError.FailedToStart:
            self.status.setText("Could not start Houdini's background renderer: " + self.process.errorString())
            self.terminal_event = True
            self.process_finished(-1)

    def process_finished(self, code, *args):
        if self.process is None:
            return
        self.read_output()
        if not self.terminal_event:
            self.status.setText(f"Renderer exited unexpectedly ({code}). Check the log; the dataset can be resumed.")
        self.log.appendPlainText(self.status.text())
        self.process.deleteLater()
        self.process = None
        self.controls.setEnabled(True)
        self.stop_button.setEnabled(False)
        for path in (self.stop_file, self.job_file):
            if path and path.exists():
                path.unlink()

    def request_stop(self, *args):
        if self.process is not None:
            self.stop_file.write_text("stop", encoding="ascii")
            self.stop_button.setEnabled(False)
            self.status.setText("Waiting for the current Karma image to finish...")

    @action
    def open_output(self):
        folder = Path(self.output.text()).expanduser().resolve()
        if not self.output.text().strip() or not folder.is_dir():
            raise ValueError("The output folder does not exist yet.")
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    @action
    def open_workbench(self):
        root = Path(__file__).resolve().parents[3]
        python = root / ".envs/workbench/Scripts/pythonw.exe"
        entry = root / "workbench/main.py"
        if not python.is_file() or not entry.is_file():
            raise ValueError("The training workbench is not installed next to this plugin.")
        folder = Path(self.output.text().strip()).expanduser().resolve()
        manifest = folder / "capture_manifest.json"
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("status") != "complete":
            raise ValueError("Finish the full dataset before opening the training workbench.")
        environment = dict(os.environ)
        for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                     "QML2_IMPORT_PATH", "QML_IMPORT_PATH", "QT_QPA_PLATFORM"):
            environment.pop(name, None)
        subprocess.Popen([str(python), str(entry), "--dataset", str(folder)], cwd=str(root),
                         env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        self.log.appendPlainText("Capture sent to the training workbench.")

    def save_preferences(self):
        values = {name: getattr(self, name).text() for name in ("source", "targets", "output", "revision", "holdout")}
        values.update({name: getattr(self, name).value() for name in
                       ("start", "end", "step", "focal", "margin", "low", "high", "samples")})
        values.update(engine=self.engine.currentIndex(), display=self.display.currentText(), view=self.view.currentText())
        dataset.write_json(self.preferences, values)

    def load_preferences(self):
        if not self.preferences.is_file():
            return
        try:
            values = json.loads(self.preferences.read_text(encoding="utf-8"))
            for name in ("source", "targets", "output", "revision", "holdout"):
                getattr(self, name).setText(values[name])
            for name in ("start", "end", "step", "focal", "margin", "low", "high", "samples"):
                getattr(self, name).setValue(values[name])
            self.engine.setCurrentIndex(values["engine"])
            self.display.setCurrentText(values["display"])
            self.view.setCurrentText(values["view"])
        except (KeyError, TypeError, ValueError):
            self.log.appendPlainText("Saved preferences could not be loaded. Using defaults.")

    def closeEvent(self, event):
        if self.process is not None:
            self.request_stop()
            event.ignore()
        else:
            self.save_preferences()
            event.accept()


def show():
    global _window
    if _window is None or not isValid(_window):
        _window = CapturePanel(hou.qt.mainWindow())
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window
