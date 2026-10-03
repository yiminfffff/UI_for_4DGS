"""Embedded interactive HUST viewer with Maya-style navigation."""
import base64
import json
import math
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from . import core
from .view_camera import orbit_pose, duration, snapshots


class Canvas(QtWidgets.QLabel):
    changed = QtCore.Signal()
    navigated = QtCore.Signal()

    def __init__(self):
        super().__init__("Load a trained run or start training to view Gaussians")
        self.setObjectName("Image")
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(150, 170)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.image = None
        self.reset()

    def reset(self, position=None):
        position = position or [3.5, 0, 1.2]
        self.target = [0.0, 0.0, 0.0]
        self.distance = math.sqrt(sum(x * x for x in position))
        self.yaw = math.atan2(position[1], position[0])
        self.pitch = math.asin(position[2] / self.distance)
        self.changed.emit()

    def apply_pose(self, pose):
        position = [pose[i][3] for i in range(3)]
        back = [pose[i][2] for i in range(3)]
        self.distance = max(0.05, math.sqrt(sum(x*x for x in position)))
        self.target = [position[i] - self.distance*back[i] for i in range(3)]
        self.yaw = math.atan2(back[1], back[0])
        self.pitch = math.asin(max(-1, min(1, back[2])))

    def pose(self):
        return orbit_pose(self.target, self.yaw, self.pitch, self.distance)

    def mousePressEvent(self, event):
        self.setFocus()
        self.last = event.position()

    def mouseMoveEvent(self, event):
        if not hasattr(self, "last"):
            return
        delta = event.position() - self.last
        self.last = event.position()
        if not event.modifiers() & QtCore.Qt.KeyboardModifier.AltModifier:
            return
        buttons = event.buttons()
        if buttons & QtCore.Qt.MouseButton.LeftButton:
            self.yaw -= delta.x() * 0.008
            self.pitch = max(-1.55, min(1.55, self.pitch + delta.y() * 0.008))
        elif buttons & QtCore.Qt.MouseButton.MiddleButton:
            pose = self.pose()
            scale = self.distance * 0.002
            self.target = [self.target[i] + (-delta.x() * pose[i][0] + delta.y() * pose[i][1]) * scale for i in range(3)]
        elif buttons & QtCore.Qt.MouseButton.RightButton:
            self.distance = max(0.05, min(500, self.distance * math.exp((delta.x() + delta.y()) * 0.008)))
        else:
            return
        self.navigated.emit()
        self.changed.emit()

    def wheelEvent(self, event):
        self.navigated.emit()
        self.distance = max(0.05, min(500, self.distance * math.exp(-event.angleDelta().y() / 1200)))
        self.changed.emit()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_F:
            self.navigated.emit()
            self.reset()
        else:
            super().keyPressEvent(event)

    def display(self, data):
        self.image = QtGui.QPixmap()
        self.image.loadFromData(data)
        self.refresh()

    def refresh(self):
        if self.image:
            self.setPixmap(self.image.scaled(self.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                            QtCore.Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


class Viewer(QtWidgets.QWidget):
    time_changed = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.ready = self.pending = self.dirty = False
        self.run = self.config = None
        self.buffer = b""
        self.request_id = 0
        self.playing = False
        self.live = False
        self.source_record = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.snapshot = QtWidgets.QComboBox()
        self.snapshot.setToolTip("Saved fine-stage iteration")
        self.snapshot.currentIndexChanged.connect(self.reload)
        row.addWidget(self.snapshot)
        self.resolution = QtWidgets.QComboBox()
        self.resolution.addItems(["512", "800", "1024"])
        self.resolution.currentIndexChanged.connect(self.invalidate)
        row.addWidget(self.resolution)
        self.home = QtWidgets.QPushButton("Reset View (F)")
        self.home.clicked.connect(self.reset_view)
        row.addWidget(self.home)
        self.match = QtWidgets.QCheckBox("Match Source Camera")
        self.match.setChecked(True)
        self.match.setToolTip("Follow the selected source camera. Navigate in the preview to switch to free view.")
        self.match.toggled.connect(self.match_source)
        row.addWidget(self.match)
        layout.addLayout(row)
        self.canvas = Canvas()
        self.canvas.changed.connect(self.invalidate)
        self.canvas.navigated.connect(lambda: self.match.setChecked(False))
        layout.addWidget(self.canvas, 1)
        row = QtWidgets.QHBoxLayout()
        self.play = QtWidgets.QPushButton("Play")
        self.play.clicked.connect(self.toggle_play)
        row.addWidget(self.play)
        self.timeline = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.timeline.setRange(0, 1000)
        self.timeline.valueChanged.connect(self.seek)
        row.addWidget(self.timeline, 1)
        layout.addLayout(row)
        self.info = QtWidgets.QLabel("Alt+LMB: Orbit | Alt+MMB: Pan | Alt+RMB: Dolly")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def open_run(self, run, config):
        self.shutdown()
        self.run, self.config = Path(run), config
        values = snapshots(self.run)
        self.saved_stage = "fine"
        if not values:
            values = snapshots(self.run,"coarse")
            self.saved_stage = "coarse"
        if not values:
            self.info.setText("Ready to start training. No saved fine-stage snapshot yet.")
            self.canvas.image = None
            self.canvas.clear()
            return
        self.snapshot.blockSignals(True)
        self.snapshot.clear()
        for value in values:
            self.snapshot.addItem(f"{self.saved_stage.title()} {value:,}", value)
        self.snapshot.setCurrentIndex(len(values) - 1)
        self.snapshot.blockSignals(False)
        record = next(r for r in config["dataset"]["records"] if r["split"] == "test")
        self.canvas.reset([record["transform_matrix"][i][3] for i in range(3)])
        self.reload()

    def reload(self, *args):
        if self.live or self.run is None or self.snapshot.currentData() is None:
            return
        self.shutdown()
        self.buffer = b""
        self.process = QtCore.QProcess(self)
        environment = QtCore.QProcessEnvironment()
        for key, value in core.environment().items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(lambda error: self.info.setText("Viewer process error: " + self.process.errorString()) if self.process else None)
        self.info.setText("Loading snapshot on the GPU...")
        self.process.start(str(core.PYTHON), [str(core.ROOT / "workbench/viewer_worker.py"),
            "--run", str(self.run), "--iteration", str(self.snapshot.currentData()), "--stage", self.saved_stage])

    def invalidate(self, *args):
        self.dirty = True

    def seek(self, *args):
        self.play_start = time.monotonic() - self.timeline.value() / 1000 * duration(self.config) if self.config else 0
        self.invalidate()
        self.time_changed.emit(self.timeline.value()/1000)

    def set_time(self, timestamp):
        self.timeline.blockSignals(True)
        self.timeline.setValue(round(timestamp*1000))
        self.timeline.blockSignals(False)
        self.play_start = time.monotonic() - timestamp*duration(self.config) if self.config else 0
        self.invalidate()

    def reset_view(self):
        self.match.setChecked(False)
        self.canvas.reset()

    def set_source(self, record):
        self.source_record = record
        if self.match.isChecked():
            self.match_source(True)

    def match_source(self, checked):
        if checked and self.source_record:
            self.canvas.apply_pose(self.source_record["transform_matrix"])
        self.invalidate()

    def start_live(self, run, config):
        self.shutdown()
        self.run, self.config, self.live = Path(run), config, True
        self.snapshot.setEnabled(False)
        self.snapshot.blockSignals(True)
        self.snapshot.clear()
        self.snapshot.addItem("Current Training")
        self.snapshot.blockSignals(False)
        self.ready = True
        self.canvas.image = None
        self.canvas.clear()
        self.canvas.setText("Waiting for point cloud initialization...")
        self.info.setText("Waiting for point cloud initialization...")
        self.send_request()

    def send_request(self):
        self.request_id += 1
        pose = self.source_record["transform_matrix"] if self.match.isChecked() and self.source_record else self.canvas.pose()
        request = dict(id=self.request_id, pose=pose, time=self.timeline.value()/1000,
            size=int(self.resolution.currentText()), fov=self.config["dataset"]["camera_angle_x"])
        self.last_request = request
        if self.live:
            core.write_json(self.run / "live-camera.json", request)
        elif self.process:
            self.process.write((json.dumps(request)+"\n").encode("utf-8"))
        self.pending, self.dirty = True, False

    def display_event(self, event):
        self.last_frame_id = event.get("id")
        self.canvas.display(base64.b64decode(event["image"]))
        self.pending = False
        prefix = f"{event['stage'].title()} {event['iteration']:,} | " if "stage" in event else ""
        if self.live and time.monotonic() < getattr(self,"reset_until",0): prefix += "Opacity reset: recovering | "
        self.info.setText(prefix + f"t {event['time']:.3f} | Render {event['milliseconds']:.1f} ms | Alt+LMB / MMB / RMB: Orbit / Pan / Dolly")

    def reset_notice(self):
        self.reset_until = time.monotonic()+8
        self.info.setText("Opacity reset: opacity is recovering during optimization.")

    def toggle_play(self):
        self.playing = not self.playing
        self.play.setText("Pause" if self.playing else "Play")
        self.seek()

    def update(self):
        if not self.ready:
            return
        if self.playing:
            timestamp = ((time.monotonic() - self.play_start) % duration(self.config)) / duration(self.config)
            self.timeline.blockSignals(True)
            self.timeline.setValue(round(timestamp * 1000))
            self.timeline.blockSignals(False)
            self.dirty = True
            self.time_changed.emit(timestamp)
        if self.dirty and not self.pending:
            self.send_request()

    def read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if b"@VIEW@" not in line:
                continue
            event = json.loads(line.split(b"@VIEW@", 1)[1])
            if event["event"] == "ready":
                self.ready, self.dirty = True, True
            elif event["event"] == "frame":
                self.display_event(event)
            elif event["event"] == "error":
                self.info.setText(event["message"])

    def finished(self, *args):
        self.ready = self.pending = False

    def shutdown(self):
        self.live = False
        self.snapshot.setEnabled(True)
        self.ready = self.pending = self.playing = False
        self.play.setText("Play")
        if self.process:
            process, self.process = self.process, None
            process.readyReadStandardOutput.disconnect(self.read)
            process.write(b'{"action":"close"}\n')
            if not process.waitForFinished(2000):
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
