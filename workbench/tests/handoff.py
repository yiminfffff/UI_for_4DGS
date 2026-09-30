"""Verify that a busy workbench defers a Maya capture request until it is idle."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtWidgets
from gs_workbench import core
from gs_workbench.app import Workbench

source = core.read_json(core.ROOT / "maya-gs-capture/test-results/latest.json")["dataset"]
with tempfile.TemporaryDirectory(prefix="handoff_", dir=str(core.ROOT / "workbench/test-results")) as tmp:
    core.STATE = Path(tmp)
    app = QtWidgets.QApplication([])
    Workbench.check_environment = lambda self: None
    window = Workbench()
    request = core.STATE / "open-dataset.json"
    core.write_json(request, {"folder": source})
    window.busy = True; window.read_handoff(); assert request.is_file()
    window.busy = False; window.read_handoff(); assert not request.exists()
    loop = QtCore.QEventLoop()
    window.validator.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(15000, loop.quit)
    loop.exec()
    assert window.dataset and window.dataset["cameras"] == 16
    assert window.folder.text() == source
    window.close()
print("DESKTOP HANDOFF PASSED")
