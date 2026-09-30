"""English desktop UI. GPU work runs exclusively in a separate QProcess."""
import codecs
from datetime import datetime
import json
from pathlib import Path
import sys
import traceback

from PySide6 import QtCore, QtGui, QtWidgets
from . import core


STYLE = """
QMainWindow, QWidget#Root { background: #111820; color: #e3ebf2; }
QWidget { color: #dce5ed; font-family: 'Segoe UI'; font-size: 12px; }
QWidget#Sidebar, QWidget#Inputs { background: #111820; }
QFrame#Card, QGroupBox { background: #19232e; border: 1px solid #2c3947; border-radius: 8px; }
QGroupBox { margin-top: 15px; padding: 14px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #9faebb; }
QLineEdit, QSpinBox, QComboBox { background: #101922; border: 1px solid #344454; border-radius: 5px; padding: 7px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #5acbb9; }
QPushButton { background: #263646; border: 1px solid #3a4f62; border-radius: 5px; padding: 9px 12px; }
QPushButton:hover { background: #344b5e; border-color: #6d8fa8; }
QPushButton#Primary { background: #56c5b2; color: #10232a; border: none; font-weight: 700; }
QPushButton#Primary:hover { background: #75d8c8; }
QPushButton:disabled { color: #647584; background: #1b2833; border-color: #283744; }
QLabel#Muted { color: #92a6b7; }
QLabel#Metric { color: #eef6fc; font-size: 22px; font-weight: 600; }
QLabel#Image { background: #0b1118; border: 1px solid #2c3947; border-radius: 6px; color: #70879b; }
QPlainTextEdit { background: #0e151d; border: 1px solid #2b3948; border-radius: 6px; color: #a9becf; font-family: Consolas; font-size: 11px; }
QProgressBar { background: #202e3a; border: none; border-radius: 4px; min-height: 8px; text-align: center; }
QProgressBar::chunk { background: #56c5b2; border-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #17212a; width: 8px; }
QScrollBar::handle:vertical { background: #42596b; min-height: 30px; border-radius: 4px; }
QToolTip { background: #263646; color: white; border: 1px solid #567084; padding: 6px; }
QCheckBox { spacing: 8px; }
QSplitter::handle { background: #111820; }
"""


class Validator(QtCore.QThread):
    progress = QtCore.Signal(int, int)
    success = QtCore.Signal(object)
    failure = QtCore.Signal(str)

    def __init__(self, folder, stride, parent):
        super().__init__(parent)
        self.folder, self.stride = folder, stride

    def run(self):
        try:
            result = core.validate_dataset(self.folder, self.stride, self.progress.emit, self.isInterruptionRequested)
            self.success.emit(result)
        except Exception as exc:
            self.failure.emit(str(exc))


class ImageView(QtWidgets.QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("Image")
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(150, 170)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Expanding)
        self.original = None

    def load(self, path, background="white"):
        if not path or not Path(path).is_file():
            self.original = None; self.setText("No image available"); return
        image = QtGui.QImage.fromData(Path(path).read_bytes())
        if image.isNull():
            self.original = None; self.setText("Unable to decode image"); return
        composed = QtGui.QImage(image.size(), QtGui.QImage.Format.Format_RGB32)
        composed.fill(QtGui.QColor(background))
        painter = QtGui.QPainter(composed); painter.drawImage(0, 0, image); painter.end()
        self.original = QtGui.QPixmap.fromImage(composed)
        self.refresh()

    def refresh(self):
        if self.original:
            self.setPixmap(self.original.scaled(self.size() - QtCore.QSize(12, 12),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event); self.refresh()


class Workbench(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("4DGS Workbench")
        self.resize(1280, 920)
        self.setMinimumSize(1040, 760)
        self.dataset = None
        self.run_folder = None
        self.config = None
        self.process = None
        self.validator = None
        self.render_frames = []
        self.source_frames = []
        self.busy = False
        self.closing = False
        self.log_stream = None
        self.build_ui()
        self.load_preferences()
        self.refresh_history()
        self.handoff_timer = QtCore.QTimer(self)
        self.handoff_timer.timeout.connect(self.read_handoff)
        self.handoff_timer.start(1000)
        QtCore.QTimer.singleShot(100, self.check_environment)

    def build_ui(self):
        from .layout import build
        build(self, ImageView)

    @staticmethod
    def label(text, muted=False):
        widget = QtWidgets.QLabel(text)
        if muted: widget.setObjectName("Muted")
        return widget

    @staticmethod
    def spin(low, high, value):
        widget = QtWidgets.QSpinBox(); widget.setRange(low, high); widget.setValue(value); return widget

    def button(self, text, action, primary=False):
        button = QtWidgets.QPushButton(text)
        if primary: button.setObjectName("Primary")
        button.clicked.connect(lambda: self.guard(action)); return button

    def guard(self, action):
        try: action()
        except Exception as exc:
            self.log.appendPlainText(str(exc)); traceback.print_exc()
            QtWidgets.QMessageBox.warning(self, "4DGS Workbench", str(exc))

    def invalidate_dataset(self):
        self.dataset = None; self.data_info.setText("Dataset changed. Validate before starting a new run.")

    def browse_dataset(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Capture Dataset Folder", self.folder.text(),
            options=QtWidgets.QFileDialog.Option.ShowDirsOnly | QtWidgets.QFileDialog.Option.DontUseNativeDialog)
        if folder: self.folder.setText(folder); self.validate()

    def use_sample(self):
        self.folder.setText(str(core.REPO / "data/dnerf/bouncingballs")); self.render_mode.setCurrentIndex(1); self.validate()

    def browse_output(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Parent Folder for Runs", self.output.text(),
            options=QtWidgets.QFileDialog.Option.ShowDirsOnly | QtWidgets.QFileDialog.Option.DontUseNativeDialog)
        if folder: self.output.setText(folder)

    def apply_preset(self, name):
        if name not in core.PRESETS: return
        self.applying_preset = True
        coarse, fine = core.PRESETS[name]; self.coarse.setValue(coarse); self.fine.setValue(fine)
        self.interval.setValue(20 if name == "Smoke Test" else 500 if name == "Quick Preview" else 1000)
        self.applying_preset = False

    def mark_custom(self):
        if not self.applying_preset:
            self.preset.setCurrentText("Custom")

    def validate(self):
        if self.busy or (self.validator and self.validator.isRunning()): return
        if not self.folder.text().strip(): raise ValueError("Choose a dataset folder first.")
        self.validate_button.setEnabled(False); self.start_button.setEnabled(False)
        self.status.setText("Decoding images and checking camera data…")
        self.validator = Validator(self.folder.text(), self.stride.value(), self)
        self.validator.progress.connect(lambda done, total: self.status.setText(f"Checking images: {done:,} / {total:,}"))
        self.validator.success.connect(self.validated)
        self.validator.failure.connect(self.validation_failed)
        self.validator.finished.connect(self.validation_finished)
        self.validator.start()

    def validated(self, result):
        # Ignore a completed scan if the user changed its input while it was running.
        if str(Path(self.folder.text()).resolve()) != result["folder"] or self.stride.value() != self.validator.stride: return
        self.dataset = result
        self.data_info.setText(f"{result['kind']}\n{result['train_images']:,} train / {result['test_images']:,} validation images\n"
            f"{result['times']} time samples · {result['cameras']} cameras\nEstimated training RAM: ~{result['estimated_ram_gb']:.1f} GB")
        self.grid.setValue(max(3, min(150, result["times"] // 2)))
        self.camera.blockSignals(True); self.camera.clear(); self.camera.addItems(sorted({r["camera"] for r in result["records"]})); self.camera.blockSignals(False)
        self.update_frame_list(); self.status.setText("Dataset validated. Configure a new run or load an existing one.")
        self.save_preferences()

    def validation_failed(self, message):
        self.dataset = None; self.status.setText("Validation failed"); self.data_info.setText(message); self.log.appendPlainText(message)

    def validation_finished(self):
        self.validate_button.setEnabled(not self.busy); self.start_button.setEnabled(not self.busy)

    def settings(self):
        return dict(coarse=self.coarse.value(), fine=self.fine.value(), checkpoint_every=self.interval.value(),
                    stride=self.stride.value(), sh_degree=self.sh.value(), temporal_grid=self.grid.value(),
                    background=self.background.currentText().lower(), opacity_deformation=self.opacity.isChecked())

    def start_training(self):
        if self.busy: return
        if not self.dataset: raise ValueError("Validate the dataset before starting training.")
        folder = Path(self.output.text()).expanduser().resolve() / core.safe_name(self.name.text().strip())
        self.config = core.create_run(folder, self.dataset, self.settings())
        self.run_folder = folder; self.remember_run(folder); self.log.clear()
        self.launch("train")

    def resume(self):
        if not self.run_folder:
            raise ValueError("Open a saved workbench run first.")
        status = core.read_json(self.run_folder / "status.json")
        if status.get("status") == "complete":
            raise ValueError("This run is complete. Create a new run to use different training settings.")
        self.launch("resume" if (self.run_folder / "latest.pt").is_file() else "train")

    def check_environment(self):
        if self.busy: return
        self.launch("check")

    def launch(self, action, options=None):
        if self.busy: raise ValueError("Wait for the current operation to finish.")
        if action != "check": self.close_viewer()
        if action != "check" and not core.PYTHON.is_file(): raise ValueError("The HUST Python environment was not found. Open Training Environment for setup instructions.")
        args = [str(core.ROOT / "workbench/worker.py"), action]
        if action == "check": args = [str(core.ROOT/"workbench/gpu_check.py")]
        if action == "ue":
            args = [str(core.ROOT / "workbench/ue_bridge.py")]
            for key, value in options.items():
                args += ["--" + key, str(value)]
        if action != "check":
            self.config = core.load_run(self.run_folder)
            stop = self.run_folder / "stop.request"
            if stop.exists(): stop.unlink()
            args += ["--run", str(self.run_folder)]
            if action == "render": args += ["--mode", "validation" if self.render_mode.currentIndex() == 0 else "orbit", "--fps", str(self.fps.value())]
            if action in ("train", "resume"):
                self.viewer.start_live(self.run_folder, self.config)
                self.show_frame(self.slider.value())
                args += ["--live-preview"]
            self.log_stream = (self.run_folder / "worker.log").open("a", encoding="utf-8")
        self.action = action; self.buffer = ""; self.decoder = codecs.getincrementaldecoder("utf-8")("replace"); self.last_event = None
        self.process = QtCore.QProcess(self); self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        environment = QtCore.QProcessEnvironment()
        for key, value in core.environment().items(): environment.insert(key, value)
        self.process.setProcessEnvironment(environment); self.process.setWorkingDirectory(str(core.ROOT if action == "check" else core.REPO))
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.set_busy(True); self.status.setText("Starting local worker…")
        self.process.start(sys.executable if action == "check" else str(core.PYTHON), args)

    def read_output(self):
        text = self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        self.buffer += text.replace("\r", "\n")
        lines = self.buffer.split("\n"); self.buffer = lines.pop()
        for line in lines:
            if self.log_stream and '"event": "live_frame"' not in line:
                self.log_stream.write(line + "\n"); self.log_stream.flush()
            if "@WB@" in line:
                try: self.handle_event(json.loads(line.split("@WB@", 1)[1]))
                except (ValueError, KeyError): self.log.appendPlainText(line)
            elif line.strip(): self.log.appendPlainText(line)

    def handle_event(self, item):
        kind = item["event"]; self.last_event = kind
        if kind == "gpu":
            self.environment_label.setText(f"{item['gpu']} | {item['vram_gb']} GB | Driver {item['driver']} | CUDA backend checked separately")
            self.check_button.setText("GPU: Ready"); self.check_button.setToolTip(self.environment_label.text())
            self.status.setText("NVIDIA GPU detected. Training Environment checks CUDA rendering.")
        elif kind == "environment":
            self.environment_label.setText(f"{item['gpu']}  ·  {item['vram_gb']} GB\nPyTorch {item['torch']} / CUDA {item['cuda']}")
            self.status.setText("GPU and CUDA extensions are ready.")
            self.check_button.setText("GPU: Ready")
            self.check_button.setToolTip(self.environment_label.text())
        elif kind == "live_frame": self.viewer.display_event(item)
        elif kind == "live_error":
            self.viewer.pending = False
            self.viewer.info.setText(item["message"])
            self.log.appendPlainText(item["message"])
        elif kind in ("status", "error", "stopped", "complete"):
            self.status.setText(item.get("message", kind)); self.log.appendPlainText(item.get("message", kind))
            if kind == "complete": self.metrics["stage"].setText("Complete")
        elif kind == "stage": self.metrics["stage"].setText(item["stage"].title())
        elif kind == "progress":
            self.metrics["stage"].setText(item["stage"].title()); self.metrics["iteration"].setText(f"{item['iteration']:,}")
            self.metrics["loss"].setText(f"{item['loss']:.4f}")
            self.metrics["psnr"].setText(f"{item['psnr']:.2f}" if item["psnr"] is not None else "—")
            self.metrics["points"].setText(f"{item['points']:,}")
            settings = self.config["settings"]
            completed = item["iteration"] + (settings["coarse"] if item["stage"] == "fine" else 0)
            self.progress.setValue(int(completed / (settings["coarse"] + settings["fine"]) * 100))
            self.status.setText(f"{item['stage'].title()} {item['iteration']:,} / {item['total']:,}  ·  GPU tensors {item['gpu_gb']:.2f} GB  ·  Session {item['elapsed']:.0f}s")
        elif kind in ("preview", "render_progress"):
            bg = self.config["settings"]["background"]
            self.result_view.load(item["path"], bg)
            if kind == "preview": self.source_view.load(item.get("source"), bg)
            if kind == "render_progress":
                self.progress.setValue(int(item["iteration"] / item["total"] * 100)); self.status.setText(f"Rendering {item['iteration']} / {item['total']}")
        elif kind == "checkpoint": self.log.appendPlainText(f"Checkpoint saved: {item['stage']} / {item['iteration']}")
        elif kind == "opacity_reset":
            self.log.appendPlainText(f"Opacity reset at {item['stage']} / {item['iteration']}. Live previews show the current model; temporary pale frames can occur while opacity recovers.")
            self.viewer.reset_notice()
        elif kind == "validation":
            if item["split"] == "test":
                self.log.appendPlainText(f"Validation PSNR: {item['psnr']:.2f} dB ({item['views']} sampled views)")
        elif kind == "render_complete":
            self.render_frames = item["frames"]
            self.status.setText("Render complete" + (f" · Selected validation camera PSNR: {item['mean_psnr']:.2f} dB" if item.get("mean_psnr") is not None else ""))
        elif kind == "ue_complete":
            self.status.setText(item["message"])
            self.log.appendPlainText(item["message"] + "\nProject: " + item["project"])

    def process_error(self, error):
        if error == QtCore.QProcess.ProcessError.FailedToStart:
            self.log.appendPlainText(self.process.errorString()); self.status.setText("Worker could not start."); self.finish_ui()

    def process_finished(self, code, status):
        self.read_output()
        if code != 0:
            self.status.setText(f"Worker stopped with exit code {code}. See the log; the last saved checkpoint is retained.")
            if self.run_folder and self.action in ("train", "resume"):
                path = self.run_folder / "status.json"
                saved = core.read_json(path)
                if saved.get("status") not in ("failed", "complete"):
                    core.write_json(path, dict(saved, status="interrupted"))
        elif self.last_event not in ("complete", "render_complete", "ue_complete", "stopped", "environment", "gpu"):
            self.status.setText("Worker finished. Check the log for details.")
        self.finish_ui()
        if self.action != "check" and self.run_folder and not self.closing:
            self.open_saved_viewer()

    def finish_ui(self):
        if self.log_stream: self.log_stream.close(); self.log_stream = None
        self.set_busy(False); self.refresh_history()
        if self.run_folder:
            self.run_info.setText("Selected run: " + self.run_folder.name)
            self.run_info.setToolTip(str(self.run_folder))
        if self.closing: self.close()

    def set_busy(self, busy):
        self.busy = busy; self.inputs.setEnabled(not busy); self.start_button.setEnabled(not busy); self.check_button.setEnabled(not busy)
        self.history.setEnabled(not busy)
        self.training_check.setEnabled(not busy); self.plugin_check.setEnabled(not busy)
        has_run = bool(self.run_folder)
        complete = has_run and core.read_json(self.run_folder / "status.json").get("status") == "complete"
        has_checkpoint = has_run and (self.run_folder / "latest.pt").is_file()
        self.resume_button.setText("Resume Run" if has_checkpoint else "Start Saved Run")
        self.resume_button.setEnabled(not busy and has_run and not complete)
        self.render_button.setEnabled(not busy and has_run and bool(list((self.run_folder / "model/point_cloud").glob("iteration_*"))))
        self.video_button.setEnabled(not busy and has_run and (self.run_folder / "latest_render.json").is_file())
        self.ue_button.setEnabled(self.render_button.isEnabled())
        self.stop_button.setEnabled(busy and getattr(self, "action", "check") != "check")
        self.force_button.setEnabled(busy and getattr(self, "action", "") != "ue")
        self.force_button.setVisible(self.force_button.isEnabled())
        self.stop_button.setText({"render": "Stop Render", "ue": "Stop Export"}.get(getattr(self, "action", ""), "Stop & Save"))

    def stop(self):
        if self.busy and self.run_folder and self.action != "check":
            (self.run_folder / "stop.request").write_text("stop", encoding="ascii")
            self.stop_button.setEnabled(False)
            self.status.setText("Stop requested. An active Unreal import must finish safely." if self.action == "ue" else "Stop requested. Waiting for a safe checkpoint boundary…")

    def force_stop(self):
        if not self.busy: return
        answer = QtWidgets.QMessageBox.question(self, "Force Stop", "Stop immediately? Work since the last saved checkpoint will be lost.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No, QtWidgets.QMessageBox.StandardButton.No)
        if answer == QtWidgets.QMessageBox.StandardButton.Yes: self.process.kill()

    def browse_run(self):
        if self.busy: return
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Open Workbench Run", str(core.RUNS),
            options=QtWidgets.QFileDialog.Option.ShowDirsOnly | QtWidgets.QFileDialog.Option.DontUseNativeDialog)
        if folder: self.load_run(folder)

    def load_selected(self):
        if not self.busy and self.history.currentData(): self.load_run(self.history.currentData())

    def load_run(self, folder):
        self.close_viewer()
        config = core.load_run(folder); self.run_folder = Path(folder).resolve(); self.config = config
        self.folder.setText(config["dataset"]["folder"])
        s = config["settings"]
        for widget, key in ((self.stride, "stride"), (self.coarse, "coarse"), (self.fine, "fine"), (self.interval, "checkpoint_every"), (self.grid, "temporal_grid"), (self.sh, "sh_degree")):
            widget.setValue(s[key])
        self.background.setCurrentText(s["background"].title()); self.opacity.setChecked(s.get("opacity_deformation", False))
        self.dataset = config["dataset"]
        self.data_info.setText(f"Loaded run: {self.run_folder.name}\nSource integrity will be rechecked by the worker.")
        self.camera.clear(); self.camera.addItems(sorted({r["camera"] for r in self.dataset["records"]}))
        self.run_info.setText("Selected run: " + self.run_folder.name); self.run_info.setToolTip(str(self.run_folder))
        self.status.setText("Run loaded. Resume and render use its saved configuration.")
        self.render_frames = core.read_json(self.run_folder / "latest_render.json")["frames"] if (self.run_folder / "latest_render.json").is_file() else []
        self.update_frame_list(); self.set_busy(False); self.remember_run(self.run_folder)
        if (self.run_folder / "preview.png").is_file(): self.result_view.load(self.run_folder / "preview.png", s["background"])
        self.name.setText(self.run_folder.name + "-new")
        self.open_saved_viewer()

    def render_result(self):
        if not self.run_folder: raise ValueError("Train or open a run first.")
        dialog = QtWidgets.QDialog(self); dialog.setWindowTitle("Export Video")
        form = QtWidgets.QFormLayout(dialog)
        mode = QtWidgets.QComboBox(); mode.addItems(["Source validation camera", "Camera orbit"])
        mode.setCurrentIndex(self.render_mode.currentIndex()); fps = self.spin(1,120,self.fps.value())
        form.addRow("Camera",mode); form.addRow("FPS",fps)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted: return
        self.render_mode.setCurrentIndex(mode.currentIndex()); self.fps.setValue(fps.value())
        self.launch("render")

    def add_to_unreal(self):
        from .ue_dialog import choose
        if self.busy or not self.run_folder:
            raise ValueError("Open a completed run and wait for the current operation to finish.")
        options = choose(self, self.run_folder)
        if options:
            self.launch("ue", options)

    def close_viewer(self):
        self.viewer.shutdown()

    def toggle_viewer(self):
        self.open_saved_viewer()

    def open_saved_viewer(self):
        if self.busy:
            return
        if not self.run_folder:
            return
        self.viewer.open_run(self.run_folder, core.load_run(self.run_folder))
        self.show_frame(self.slider.value())

    def update_frame_list(self):
        self.source_frames = [r for r in self.dataset["records"] if r["camera"] == self.camera.currentText()] if self.dataset else []
        self.frames = sorted(self.source_frames, key=lambda r:r["time"])
        self.slider.setRange(0, max(0, len(self.frames) - 1)); self.show_frame(self.slider.value())

    def show_frame(self, index):
        frames = getattr(self, "frames", [])
        if not frames: self.frame_label.setText("No frames"); return
        record = frames[min(index, len(frames) - 1)]
        bg = self.background.currentText().lower()
        self.source_view.load(record["image"], bg)
        self.viewer.set_source(record)
        self.viewer.set_time(float(record["time"]))
        self.frame_label.setText(f"{index + 1} / {len(frames)}  ·  t {record['time']:.3f}")

    def sync_source_time(self, timestamp):
        if self.viewer.playing:
            self.play_timer.stop(); self.play.setText("Play")
        frames = getattr(self, "frames", [])
        if not frames: return
        index = min(range(len(frames)), key=lambda i:abs(frames[i]["time"]-timestamp))
        self.slider.blockSignals(True); self.slider.setValue(index); self.slider.blockSignals(False)
        self.source_view.load(frames[index]["image"], self.background.currentText().lower())
        self.frame_label.setText(f"{index+1} / {len(frames)}  ·  t {frames[index]['time']:.3f}")

    def toggle_play(self):
        if self.play_timer.isActive(): self.play_timer.stop(); self.play.setText("Play")
        else:
            self.viewer.playing = False; self.viewer.play.setText("Play")
            fps = (self.dataset or {}).get("fps",24)
            self.play_timer.start(max(8,int(1000/fps))); self.play.setText("Pause")

    def open_training_environment(self):
        from .maintenance import TrainingDialog
        TrainingDialog(self).exec()

    def open_ue_plugin(self):
        from .maintenance import PluginDialog
        PluginDialog(self).exec()

    def open_video(self):
        if self.run_folder and (self.run_folder / "latest_render.json").is_file():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(core.read_json(self.run_folder / "latest_render.json")["video"]))

    def open_run_folder(self):
        if self.run_folder: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.run_folder)))

    def remember_run(self, folder):
        path = core.STATE / "recent.json"
        old = core.read_json(path) if path.is_file() else []
        core.write_json(path, [str(folder)] + [p for p in old if p != str(folder)][:19]); self.refresh_history()

    def refresh_history(self):
        path = core.STATE / "recent.json"; self.history.clear()
        try:
            folders = core.read_json(path) if path.is_file() else []
            if not isinstance(folders, list):
                raise ValueError("Recent runs must be a list.")
        except (OSError, ValueError) as exc:
            self.log.appendPlainText("Could not read recent runs: " + str(exc))
            return
        for folder in folders:
            try:
                if not (Path(folder) / "run.json").is_file():
                    continue
                status_path = Path(folder) / "status.json"
                status = core.read_json(status_path).get("status", "unknown") if status_path.is_file() else "ready"
                self.history.addItem(f"{Path(folder).name} · {status}", folder)
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                self.log.appendPlainText(f"Skipped an unavailable recent run: {folder} ({exc})")

    def save_preferences(self):
        core.write_json(core.STATE / "preferences.json", dict(dataset=self.folder.text(), output=self.output.text()))

    def read_handoff(self):
        path = core.STATE / "open-dataset.json"
        if self.busy or (self.validator and self.validator.isRunning()) or not path.is_file():
            return
        try:
            folder = core.read_json(path)["folder"]
            path.unlink()
            self.close_viewer()
            self.run_folder = None; self.config = None; self.render_frames = []
            self.run_info.setText("New capture received")
            self.folder.setText(folder); self.set_busy(False)
            self.showNormal(); self.raise_(); self.activateWindow(); self.validate()
        except Exception as exc:
            self.log.appendPlainText("Could not open the capture request: " + str(exc))

    def load_preferences(self):
        path = core.STATE / "preferences.json"
        if path.is_file():
            data = core.read_json(path); self.folder.setText(data.get("dataset", "")); self.output.setText(data.get("output", str(core.RUNS)))

    def closeEvent(self, event):
        self.close_viewer()
        if self.validator and self.validator.isRunning():
            self.validator.requestInterruption(); self.status.setText("Finishing image validation before closing…")
            self.validator.finished.connect(self.close); event.ignore(); return
        if self.busy:
            self.closing = True
            if self.action == "check": self.process.kill()
            else: self.stop()
            event.ignore(); return
        self.save_preferences(); event.accept()


def apply_theme(app):
    app.setStyle("Fusion"); app.setStyleSheet(STYLE)
    palette = QtGui.QPalette()
    for role, color in (("Window", "#111820"), ("WindowText", "#dce5ed"), ("Base", "#101922"),
                        ("AlternateBase", "#19232e"), ("Text", "#dce5ed"), ("Button", "#263646"),
                        ("ButtonText", "#dce5ed"), ("Highlight", "#56c5b2"), ("HighlightedText", "#10232a")):
        palette.setColor(getattr(QtGui.QPalette.ColorRole, role), QtGui.QColor(color))
    app.setPalette(palette)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset")
    args = parser.parse_args()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("4DGS Workbench"); apply_theme(app)
    core.STATE.mkdir(parents=True, exist_ok=True)
    if args.dataset:
        core.write_json(core.STATE / "open-dataset.json", {"folder": str(Path(args.dataset).resolve())})
    lock = QtCore.QLockFile(str(core.STATE / "desktop.lock"))
    if not lock.tryLock(100):
        if not args.dataset:
            QtWidgets.QMessageBox.information(None, "4DGS Workbench", "The workbench is already open.")
        return 0
    window = Workbench(); window.show()
    return app.exec()
