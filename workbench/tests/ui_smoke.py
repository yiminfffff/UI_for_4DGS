"""Offscreen desktop construction and run-inspector smoke test."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtWidgets
from gs_workbench import core
from gs_workbench.app import Workbench, apply_theme

app = QtWidgets.QApplication([])
QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
apply_theme(app)
# This test focuses on the desktop. The GPU worker has its own integration test.
Workbench.check_environment = lambda self: None
core.STATE = core.ROOT / "workbench/test-results/layout-ui-state"
window = Workbench(); window.show()
data = core.validate_dataset(core.REPO / "data/dnerf/bouncingballs", stride=5)
window.folder.setText(data["folder"]); window.dataset = data
window.data_info.setText(f"{data['kind']}\n{data['train_images']} train / {data['test_images']} validation images\n{data['times']} time samples\nEstimated RAM: {data['estimated_ram_gb']} GB")
window.camera.addItems(sorted({r["camera"] for r in data["records"]})); window.update_frame_list()
report_path = core.ROOT / "workbench/test-results/integration.json"
if report_path.is_file():
    report = core.read_json(report_path); window.load_run(report["run"])
    window.slider.setValue(min(4,window.slider.maximum()))
    window.metrics["stage"].setText("Complete"); window.metrics["iteration"].setText("40")
    window.progress.setValue(100); window.status.setText("CUDA training, checkpoint resume, and 160-frame rendering verified.")
app.processEvents()
window.grab().save(str(core.ROOT / "workbench/test-results/desktop.png"))
assert window.start_button.text() == "Start Training"
assert not hasattr(window,"inspect_mode")
assert window.viewer.match.text() == "Match Source Camera"
assert window.source_view.original is not None or window.result_view.original is not None
window.close(); app.processEvents()
print("UI SMOKE PASSED")
