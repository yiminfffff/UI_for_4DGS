"""Startup must tolerate unavailable or malformed recent-run entries."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_workbench.app import Workbench


class StartupTests(unittest.TestCase):
    def test_unavailable_history_does_not_hide_valid_run(self):
        window = SimpleNamespace(history=Mock(), log=Mock())

        def exists(path):
            if "blocked-run" in str(path):
                raise PermissionError("Access denied")
            return path.name in ("recent.json", "run.json")

        with patch.object(Path, "is_file", exists), patch(
                "gs_workbench.core.read_json",
                return_value=["blocked-run", None, "valid-run"]):
            Workbench.refresh_history(window)
        window.history.addItem.assert_called_once_with("valid-run · ready", "valid-run")
        self.assertEqual(window.log.appendPlainText.call_count, 2)

    def test_invalid_history_does_not_abort_startup(self):
        window = SimpleNamespace(history=Mock(), log=Mock())
        with patch.object(Path, "is_file", return_value=True), patch(
                "gs_workbench.core.read_json", side_effect=ValueError("Invalid JSON")):
            Workbench.refresh_history(window)
        window.history.addItem.assert_not_called()
        window.log.appendPlainText.assert_called_once()


if __name__ == "__main__":
    unittest.main()
