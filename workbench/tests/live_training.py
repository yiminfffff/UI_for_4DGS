"""Exercise initialization, same-process training preview, camera matching and live navigation."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile
import time
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore,QtGui,QtWidgets
from gs_workbench import core
from gs_workbench.app import Workbench,apply_theme

out = core.ROOT/"workbench/test-results"
root = Path(tempfile.mkdtemp(prefix="live_train_",dir=out))
core.STATE = root/"state"
app = QtWidgets.QApplication([]); QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf"); apply_theme(app)
Workbench.check_environment = lambda self:None
window = Workbench(); window.resize(1500,1000); window.show()
data = core.validate_dataset(core.REPO/"data/dnerf/bouncingballs",stride=5)
window.folder.setText(data["folder"]); window.validated(data) if window.validator else None
window.dataset = data; window.camera.addItems(sorted({r["camera"] for r in data["records"]})); window.update_frame_list()
window.stride.setValue(5); window.dataset = data
window.output.setText(str(root)); window.name.setText("live-preview")
window.coarse.setValue(30); window.fine.setValue(40); window.interval.setValue(20); window.grid.setValue(10)
events = []; original = window.handle_event
def handle(event):
    original(event)
    if event["event"] == "live_frame":
        events.append({k:v for k,v in event.items() if k != "image"})
        assert window.viewer.process is None, "A second GPU viewer was started during training"
        if len(events) == 1:
            request = core.read_json(window.run_folder/"live-camera.json")
            assert request["pose"] == window.frames[window.slider.value()]["transform_matrix"]
            window.viewer.canvas.last = QtCore.QPointF(100,100)
            mouse = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove,QtCore.QPointF(170,125),QtCore.QPointF(170,125),
                QtCore.Qt.MouseButton.NoButton,QtCore.Qt.MouseButton.LeftButton,QtCore.Qt.KeyboardModifier.AltModifier)
            window.viewer.canvas.mouseMoveEvent(mouse)
            assert not window.viewer.match.isChecked()
            window.viewer.resolution.setCurrentText("800")
window.handle_event = handle
window.start_training(); deadline = time.monotonic()+300

def tick():
    try:
        assert time.monotonic()<deadline, window.log.toPlainText()[-3000:]
        if not window.busy:
            assert window.last_event=="complete",window.log.toPlainText()[-3000:]
            assert any(e["stage"]=="coarse" and e["iteration"]==0 for e in events),events
            assert any(e["stage"]=="fine" and e["iteration"]==0 for e in events),events
            assert any(e["id"]>events[0]["id"] for e in events),events
            window.grab().save(str(out/"live-training-layout.png"))
            core.write_json(out/"live-training.json",dict(status="passed",run=str(window.run_folder),events=events,
                source_match=True,navigation=True,same_process=True))
            timer.stop();window.close();app.quit()
    except Exception:
        core.write_json(out/"live-training.json",dict(status="failed",error=traceback.format_exc(),events=events))
        timer.stop()
        if window.busy:window.process.kill();window.process.waitForFinished(3000)
        window.close();app.exit(1)
timer = QtCore.QTimer();timer.timeout.connect(tick);timer.start(80)
sys.exit(app.exec())
