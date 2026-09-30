"""Exercise the actual workbench Unreal action in the isolated test project."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtWidgets
from gs_workbench import core, ue_dialog
from gs_workbench.app import Workbench, apply_theme

app = QtWidgets.QApplication([])
QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
apply_theme(app)
core.STATE = core.ROOT / "workbench/test-results/ue-ui-state"
Workbench.check_environment = lambda self: None
window = Workbench()
window.resize(1500,950)
window.load_run(core.RUNS / "capture-0919-203240")
window.show()
ue_dialog.choose = lambda parent, run: dict(project=str(core.ROOT / "unreal/GS4DTest/GS4DTest.uproject"),
    engine="C:/Program Files/Epic Games/UE_5.8", iteration=20000)
window.add_to_unreal()
started = time.monotonic()

def tick():
    if not window.busy:
        success = window.last_event == "ue_complete"
        core.write_json(core.ROOT / "workbench/test-results/ue-workflow.json",
            dict(status="passed" if success else "failed", message=window.status.text(), seconds=time.monotonic()-started))
        window.grab().save(str(core.ROOT / "workbench/test-results/ue-workflow.png"))
        window.close()
        app.exit(0 if success else 1)

timer = QtCore.QTimer()
timer.timeout.connect(tick)
timer.start(250)
sys.exit(app.exec())
