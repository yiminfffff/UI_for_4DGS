"""Independent training-environment and per-project Unreal plugin maintenance panels."""
import json
from pathlib import Path
import subprocess
import sys
from PySide6 import QtCore, QtWidgets
from . import core


class TrainingDialog(QtWidgets.QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle("Training Environment"); self.resize(740,470)
        self.parent_window = parent; self.process = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Check the HUST backend, PyTorch, CUDA extensions and a small GPU render."))
        self.details = QtWidgets.QPlainTextEdit(); self.details.setReadOnly(True); layout.addWidget(self.details,1)
        self.details.setPlainText("Checking installed environment...")
        row = QtWidgets.QHBoxLayout()
        self.check_button = QtWidgets.QPushButton("Check Environment"); self.check_button.clicked.connect(self.check)
        self.repair_button = QtWidgets.QPushButton("Rebuild CUDA Extensions"); self.repair_button.clicked.connect(self.repair)
        help_button = QtWidgets.QPushButton("Setup Instructions"); help_button.clicked.connect(self.instructions)
        for button in (self.check_button,self.repair_button,help_button): row.addWidget(button)
        layout.addLayout(row); self.check()

    def instructions(self):
        self.details.setPlainText((core.ROOT/"workbench/ENVIRONMENT-SETUP.md").read_text(encoding="utf-8"))

    def start(self,program,args):
        self.buffer = ""; self.report = None
        self.check_button.setEnabled(False); self.repair_button.setEnabled(False)
        self.process = QtCore.QProcess(self); self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        env = QtCore.QProcessEnvironment()
        for key,value in core.environment().items(): env.insert(key,value)
        self.process.setProcessEnvironment(env); self.process.setWorkingDirectory(str(core.ROOT))
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(lambda error:self.details.appendPlainText(self.process.errorString()))
        self.process.start(program,args)

    def check(self):
        self.details.clear()
        if not core.PYTHON.is_file() or not (core.REPO/"train.py").is_file():
            self.parent_window.training_check.setText("Training Environment: Missing")
            self.instructions(); self.repair_button.setEnabled(False); return
        self.start(str(core.PYTHON),[str(core.ROOT/"workbench/backend_check.py")])

    def repair(self):
        self.details.setPlainText("Rebuilding the two installed CUDA extensions. Training must remain stopped.")
        self.start("cmd.exe",["/d","/c",str(core.ROOT/"build-hust.cmd")])

    def read(self):
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8",errors="replace")
        self.buffer += text; self.details.moveCursor(self.details.textCursor().MoveOperation.End); self.details.insertPlainText(text)
        for line in self.buffer.splitlines():
            if "@MAINT@" in line:
                try: self.report = json.loads(line.split("@MAINT@",1)[1])
                except ValueError: continue

    def finished(self,code,status):
        self.read()
        for line in self.buffer.splitlines():
            if "@MAINT@" in line:
                self.report = json.loads(line.split("@MAINT@",1)[1])
        result = self.report or dict(status="Not Checked" if code == 0 else "Needs Repair",message="Run Check Environment to verify the repair.")
        self.parent_window.training_check.setText("Training Environment: "+result["status"])
        self.parent_window.training_check.setToolTip(result["message"])
        if result["status"] == "Ready":
            self.details.setPlainText("Ready\n\n"+result["message"]+f"\n\nGPU: {result['gpu']}\nPyTorch: {result['torch']}\nCUDA: {result['cuda']}\n\nNo generic pretrained model download is required. Each capture is trained as its own scene.")
        self.check_button.setEnabled(True); self.repair_button.setEnabled(result["status"] != "Ready")

    def closeEvent(self,event):
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.details.appendPlainText("Wait for the environment operation to finish before closing."); event.ignore()
        else: event.accept()

    def reject(self):
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.details.appendPlainText("Wait for the environment operation to finish before closing.")
        else: super().reject()


class PluginDialog(QtWidgets.QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle("UE Plugin"); self.resize(720,420)
        self.parent_window = parent; self.process = None
        saved = core.STATE/"ue-settings.json"; settings = core.read_json(saved) if saved.is_file() else {}
        form = QtWidgets.QFormLayout(self)
        self.project = QtWidgets.QLineEdit(settings.get("project",str(core.ROOT/"unreal/GS4DTest/GS4DTest.uproject")))
        self.engine = QtWidgets.QLineEdit(settings.get("engine","C:/Program Files/Epic Games/UE_5.8"))
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.project); browse = QtWidgets.QPushButton("Browse..."); browse.clicked.connect(self.browse); row.addWidget(browse)
        form.addRow("Project",row); form.addRow("Engine Folder",self.engine)
        self.details = QtWidgets.QPlainTextEdit(); self.details.setReadOnly(True); form.addRow(self.details)
        row = QtWidgets.QHBoxLayout(); self.check_button = QtWidgets.QPushButton("Check Plugin"); self.check_button.clicked.connect(self.check)
        self.install_button = QtWidgets.QPushButton("Install / Update Plugin"); self.install_button.clicked.connect(self.install)
        row.addWidget(self.check_button); row.addWidget(self.install_button); form.addRow(row)
        form.addRow(QtWidgets.QLabel("Close Unreal Editor before installation. Existing assets are preserved."))
        self.check()

    def browse(self):
        path,_ = QtWidgets.QFileDialog.getOpenFileName(self,"Choose UE Project",self.project.text(),"Unreal Project (*.uproject)")
        if path: self.project.setText(path); self.check()

    def check(self):
        from .plugin_status import inspect
        self.result = inspect(Path(self.project.text()),Path(self.engine.text()))
        self.details.setPlainText(self.result["message"])
        self.parent_window.plugin_check.setText("UE Plugin: "+self.result["status"])
        self.install_button.setEnabled(self.result.get("can_install",False))
        if Path(self.project.text()).is_file():
            core.write_json(core.STATE/"ue-settings.json",dict(project=self.project.text(),engine=self.engine.text()))

    def install(self):
        self.process = QtCore.QProcess(self); self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(lambda:self.details.insertPlainText(bytes(self.process.readAllStandardOutput()).decode("utf-8",errors="replace")))
        self.process.finished.connect(self.installed); self.process.errorOccurred.connect(lambda error:self.details.appendPlainText(self.process.errorString()))
        self.install_button.setEnabled(False); self.check_button.setEnabled(False)
        self.process.start(sys.executable,[str(core.ROOT/"workbench/ue_bridge.py"),"--install-only","--project",self.project.text(),"--engine",self.engine.text()])

    def installed(self,code,status):
        self.check_button.setEnabled(True)
        if code == 0: self.check()
        else: self.install_button.setEnabled(True); self.parent_window.plugin_check.setText("UE Plugin: Install Failed")

    def closeEvent(self,event):
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning: event.ignore()
        else: event.accept()

    def reject(self):
        if self.process and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.details.appendPlainText("Wait for plugin installation to finish before closing.")
        else: super().reject()
