"""Exercise shelf installation and the real asynchronous panel workflow."""
import json
from pathlib import Path
import runpy
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import maya.cmds as cmds
from PySide6 import QtCore, QtGui, QtWidgets
from gs_capture import dataset

OUT = ROOT / "test-results"


def run():
    try:
        smoke = json.loads((OUT / "interactive/result.json").read_text(encoding="utf-8"))
        cmds.loadPlugin("mtoa")
        cmds.file(str(Path(smoke["run"]) / "scene.ma"), open=True, force=True)
        install = runpy.run_path(str(ROOT / "install.py"))["install"]
        install(); install()
        import gs_capture.ui as ui
        panel = ui._window
        children = cmds.shelfLayout("GSCapture", query=True, childArray=True)
        assert len(children) == 1, children
        panel.targets = cmds.ls("TestEffect", long=True)
        panel.target_label.setText("TestEffect")
        panel.start.setValue(1); panel.end.setValue(3); panel.step.setValue(1)
        panel.aa.setValue(1); panel.device.setCurrentIndex(0)
        panel.cached.setChecked(True)
        run_dir = Path(tempfile.mkdtemp(prefix="ui_", dir=str(OUT)))
        panel.output.setText(str(run_dir / "dataset"))
        # Do not open Explorer in an automated test.
        QtGui.QDesktopServices.openUrl = lambda url: True
        original_end = panel.end_job
        def end(message):
            original_end(message)
            try:
                assert panel.session.state["status"] == "preview_complete", message
                assert panel.finished == 3
                assert not panel.running and panel.controls.isEnabled()
                panel.grab().save(str(OUT / "panel-verified.png"))
                dataset.write_json(OUT / "ui-workflow.json", dict(status="passed", images=3,
                    installer_idempotent=True, output=str(panel.session.root), message=message))
            except Exception:
                dataset.write_json(OUT / "ui-workflow.json", dict(status="failed", error=traceback.format_exc()))
            QtCore.QTimer.singleShot(100, lambda: cmds.quit(force=True))
        panel.end_job = end
        panel.start_render(preview=True)
    except Exception:
        dataset.write_json(OUT / "ui-workflow.json", dict(status="failed", error=traceback.format_exc()))
        cmds.quit(force=True)


cmds.evalDeferred(run, lowestPriority=True)
