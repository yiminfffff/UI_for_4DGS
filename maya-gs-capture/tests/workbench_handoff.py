"""Verify the Maya handoff arguments without launching a second desktop window."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gs_capture.ui import CapturePanel

folder = json.loads((ROOT / "test-results/latest.json").read_text(encoding="utf-8"))["dataset"]
messages = []
panel = SimpleNamespace(output=SimpleNamespace(text=lambda: folder),
                        log=SimpleNamespace(appendPlainText=messages.append))
with patch.dict(os.environ, {"PYTHONHOME": "maya-python", "QT_PLUGIN_PATH": "maya-qt"}):
    with patch("subprocess.Popen") as process:
        CapturePanel.open_workbench(panel)
        argv = process.call_args.args[0]
        options = process.call_args.kwargs
        assert Path(argv[0]).is_file() and Path(argv[1]).is_file()
        assert argv[2:] == ["--dataset", folder]
        assert "PYTHONHOME" not in options["env"] and "QT_PLUGIN_PATH" not in options["env"]
        assert options["creationflags"]
assert messages == ["Capture sent to the training workbench."]
print("MAYA HANDOFF PASSED")
