"""Real desktop -> Maya-export validation -> CUDA training -> reference rendering."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtWidgets
from gs_workbench import core
from gs_workbench.app import Workbench, apply_theme

OUT = core.ROOT / "workbench/test-results"
source = core.read_json(core.ROOT / "maya-gs-capture/test-results/latest.json")["dataset"]
app = QtWidgets.QApplication([])
QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
apply_theme(app)
window = Workbench(); window.show()
stage = "gpu"
started = time.monotonic()
failed = False
run_parent = Path(tempfile.mkdtemp(prefix="desktop_", dir=str(OUT)))


def tick():
    global stage, failed
    try:
        if time.monotonic() - started > 180:
            raise RuntimeError("Desktop workflow timed out: " + stage)
        if getattr(window, "last_event", None) == "error":
            raise RuntimeError(window.log.toPlainText()[-4000:])
        if stage == "gpu" and window.process and not window.busy:
            assert "CUDA" in window.environment_label.text(), window.environment_label.text()
            stage = "validate"
            window.folder.setText(source); window.stride.setValue(1); window.validate()
        elif stage == "validate" and window.dataset and not window.validator.isRunning():
            assert window.dataset["kind"] == "Maya GS Capture"
            stage = "train"
            window.coarse.setValue(5); window.fine.setValue(10); window.interval.setValue(5)
            window.grid.setValue(3); window.output.setText(str(run_parent)); window.name.setText("maya-export-smoke")
            window.start_training()
        elif stage == "train" and not window.busy:
            assert window.last_event == "complete", window.log.toPlainText()[-4000:]
            stage = "render"
            window.render_mode.setCurrentIndex(0); window.fps.setValue(12); window.launch("render")
        elif stage == "render" and not window.busy:
            assert window.last_event == "render_complete", window.log.toPlainText()[-4000:]
            report = core.read_json(window.run_folder / "latest_render.json")
            assert len(report["frames"]) == 2
            assert all(f["source"] for f in report["frames"])
            assert window.source_view.original is not None and window.result_view.original is not None
            window.grab().save(str(OUT / "desktop-workflow.png"))
            core.write_json(OUT / "desktop-workflow.json", dict(status="passed", run=str(window.run_folder),
                gpu=window.environment_label.text(), maya_cameras=16, train_images=28, test_images=4,
                rendered_frames=2, video=report["video"], validation_camera_psnr=report["mean_psnr"]))
            timer.stop(); window.close(); app.quit()
    except Exception:
        failed = True
        core.write_json(OUT / "desktop-workflow.json", dict(status="failed", stage=stage, error=traceback.format_exc()))
        if window.process and window.busy: window.process.kill(); window.process.waitForFinished(3000)
        timer.stop(); window.close(); app.quit()


timer = QtCore.QTimer(); timer.timeout.connect(tick); timer.start(100)
app.exec()
raise SystemExit(1 if failed else 0)
