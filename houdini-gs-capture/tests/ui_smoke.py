"""Launch with houdini.exe waitforui ui_smoke.py in an isolated test profile."""
import json
from pathlib import Path
import runpy
import sys
import traceback

import hou
from PySide6 import QtCore, QtWidgets

ROOT = Path(globals().get("__file__", sys._getframe().f_code.co_filename)).resolve().parents[1]
RESULTS = ROOT / "test-results"


def start():
    try:
        runpy.run_path(str(ROOT / "install.py"), run_name="__main__")
        from gs_capture_houdini import ui
        panel = ui.show()
        panel.source.setText("/stage/animated_effect")
        panel.targets.setText("/World/Effect")
        panel.output.setText(str(RESULTS / "capture"))
        panel.cached.setChecked(True)
        panel.start.setValue(1)
        panel.end.setValue(2)
        panel.samples.setValue(4)
        panel.revision.setText("fixture-v1")
        panel.status.setText("Ready")
        def finish():
            try:
                assert panel.grab().save(str(RESULTS / "ui-preview.png"))
                labels = [w.text() for w in panel.findChildren(QtWidgets.QLabel)]
                labels += [w.text() for w in panel.findChildren(QtWidgets.QPushButton)]
                assert all(text.isascii() for text in labels), labels
                assert panel.count.text() == "32 PNG images"
                assert "gs_capture_houdini" in hou.shelves.shelves()
                (RESULTS / "ui-result.json").write_text(json.dumps(dict(passed=True, labels=labels)), encoding="utf-8")
            except Exception:
                (RESULTS / "ui-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            hou.hscript("quit")
        QtCore.QTimer.singleShot(1500, finish)
    except Exception:
        (RESULTS / "ui-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        hou.hscript("quit")


QtCore.QTimer.singleShot(1000, start)
