"""Check real backend diagnostics and install the player into an isolated project without a trained run."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore,QtGui,QtWidgets
from gs_workbench import core
from gs_workbench.app import Workbench,apply_theme
from gs_workbench.maintenance import TrainingDialog,PluginDialog
from gs_workbench.plugin_status import inspect

out = core.ROOT/"workbench/test-results"
root = Path(tempfile.mkdtemp(prefix="maintenance_",dir=out)); core.STATE = root/"state"
project = root/"Test.uproject"; core.write_json(project,dict(FileVersion=3,EngineAssociation="5.8"))
engine = Path("C:/Program Files/Epic Games/UE_5.8")
app = QtWidgets.QApplication([]); QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf"); apply_theme(app)
Workbench.check_environment = lambda self:None
window = Workbench()
assert inspect(project,engine)["status"] == "Missing"
core.write_json(core.STATE/"ue-settings.json",dict(project=str(project),engine=str(engine)))
dialog = PluginDialog(window); dialog.show(); assert dialog.install_button.isEnabled()
dialog.install(); deadline = time.monotonic()+30
while dialog.process.state() != QtCore.QProcess.ProcessState.NotRunning and time.monotonic()<deadline:
    app.processEvents();time.sleep(.01)
app.processEvents()
assert inspect(project,engine)["status"] == "Ready",dialog.details.toPlainText()
assert project.with_suffix(".uproject.before-gs4d").is_file()
dialog.close()
source_file = project.parent/"Plugins/GS4D/Source/GS4D/Private/GS4D.cpp"
source_file.write_text(source_file.read_text()+"\n// Local project edit.\n")
assert inspect(project,engine)["status"] == "Modified"
core.write_json(out/"maintenance.json",dict(status="passed",independent_install=True,project=str(project),modified_files_protected=True))
window.close()
print("MAINTENANCE PASSED")
