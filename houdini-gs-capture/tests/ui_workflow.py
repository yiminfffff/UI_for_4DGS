"""Exercise preview, asynchronous stop/resume, and full dataset handoff from the UI."""
import json
from pathlib import Path
import runpy
import sys
import time
import traceback

import hou
from PySide6 import QtCore, QtGui

ROOT = Path(globals().get("__file__", sys._getframe().f_code.co_filename)).resolve().parents[1]
RESULTS = ROOT / "test-results"
state = {"phase": "start", "started": time.monotonic(), "ticks": 0}


def fail():
    (RESULTS / "ui-workflow-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    hou.hscript("quit")


def start():
    try:
        hou.hipFile.load(str(RESULTS / "fixture.hipnc"), suppress_save_prompt=True, ignore_load_warnings=True)
        runpy.run_path(str(ROOT / "install.py"), run_name="__main__")
        from gs_capture_houdini import ui
        panel = ui.show()
        state["panel"] = panel
        panel.source.setText("/stage/animated_effect")
        panel.targets.setText("/World/Effect")
        panel.output.setText(str(RESULTS / "ui-capture"))
        panel.cached.setChecked(True)
        panel.use_timeline()
        panel.samples.setValue(4)
        panel.revision.setText("fixture-v1")
        assert panel.count.text() == "32 PNG images"
        # Keep test artifacts in the test folder without opening Explorer windows.
        QtGui.QDesktopServices.openUrl = lambda url: True
        panel.start_job(True)
        state["phase"] = "stop"
        timer = QtCore.QTimer(panel)
        timer.timeout.connect(tick)
        timer.start(100)
        state["timer"] = timer
    except Exception:
        fail()


def tick():
    try:
        state["ticks"] += 1
        panel = state["panel"]
        if time.monotonic() - state["started"] > 300:
            raise RuntimeError("UI workflow timed out: " + panel.log.toPlainText())
        phase = state["phase"]
        if phase == "stop" and panel.progress.value() >= 1:
            panel.request_stop()
            state["phase"] = "wait_stop"
        elif phase == "wait_stop" and panel.process is None:
            manifest = json.loads((RESULTS / "ui-capture_preview/capture_manifest.json").read_text(encoding="utf-8"))
            assert manifest["status"] == "cancelled", panel.log.toPlainText()
            state["stopped_after"] = len(manifest["completed"])
            state["phase"] = "resume"
            panel.start_job(True)
        elif phase == "resume" and panel.process is None:
            manifest = json.loads((RESULTS / "ui-capture_preview/capture_manifest.json").read_text(encoding="utf-8"))
            assert manifest["status"] == "preview_complete", panel.log.toPlainText()
            panel.output.setText(str(RESULTS / "capture"))
            state["phase"] = "full"
            panel.start_job(False)
        elif phase == "full" and panel.process is None:
            assert "Dataset complete" in panel.status.text(), panel.log.toPlainText()
            assert panel.grab().save(str(RESULTS / "ui-preview.png"))
            (RESULTS / "ui-workflow.log").write_text(panel.log.toPlainText(), encoding="utf-8")
            result = dict(passed=True, ticks=state["ticks"], stopped_after=state["stopped_after"],
                          preview_images=3, full_images=32, title=panel.windowTitle())
            (RESULTS / "ui-workflow-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            state["timer"].stop()
            hou.hscript("quit")
        elif panel.process is None and phase == "stop":
            raise RuntimeError("Preview did not start: " + panel.log.toPlainText())
    except Exception:
        state["timer"].stop()
        fail()


QtCore.QTimer.singleShot(1000, start)
