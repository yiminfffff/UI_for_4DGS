"""Test the actual embedded viewer and its Qt navigation handlers."""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtWidgets
from gs_workbench import core
from gs_workbench.app import Workbench, apply_theme

app = QtWidgets.QApplication([])
QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
apply_theme(app)
core.STATE = core.ROOT / "workbench/test-results/live-ui-state"
Workbench.check_environment = lambda self: None
window = Workbench()
window.resize(1500, 950)
window.load_run(core.RUNS / "capture-0919-203240")
window.show()
window.toggle_viewer()
deadline = time.monotonic() + 45
phase = 0
baseline = None


def tick():
    global phase, baseline
    try:
        assert time.monotonic() < deadline, window.viewer.info.text()
        viewer = window.viewer
        if phase == 0 and viewer.canvas.image:
            baseline = viewer.canvas.pose()
            viewer.canvas.last = QtCore.QPointF(100, 100)
            event = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(160, 125), QtCore.QPointF(160, 125),
                QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.AltModifier)
            viewer.canvas.mouseMoveEvent(event)
            assert viewer.canvas.pose() != baseline
            assert not viewer.match.isChecked()
            free_pose = viewer.canvas.pose()
            window.camera.setCurrentIndex((window.camera.currentIndex()+1)%window.camera.count())
            assert viewer.canvas.pose() == free_pose
            viewer.match.setChecked(True)
            phase = 1
        elif phase == 1 and not viewer.pending and getattr(viewer,"last_frame_id",None) == viewer.last_request["id"]:
            assert viewer.last_request["pose"] == viewer.source_record["transform_matrix"]
            viewer.match.setChecked(False)
            viewer.timeline.setValue(0)
            viewer.toggle_play()
            phase = 2
        elif phase == 2 and viewer.timeline.value() > 100 and not viewer.pending:
            viewer.toggle_play()
            window.grab().save(str(core.ROOT / "workbench/test-results/live-viewer/ui-preview.png"))
            core.write_json(core.ROOT / "workbench/test-results/live-viewer/ui.json", dict(passed=True,
                pose_changed=True, source_matched=True, free_camera_preserved=True,
                time=viewer.timeline.value()/1000, status=viewer.info.text()))
            timer.stop()
            window.close()
            app.quit()
    except Exception as exc:
        core.write_json(core.ROOT / "workbench/test-results/live-viewer/ui.json", dict(passed=False, error=str(exc)))
        timer.stop()
        window.close()
        app.exit(1)


timer = QtCore.QTimer()
timer.timeout.connect(tick)
timer.start(30)
sys.exit(app.exec())
