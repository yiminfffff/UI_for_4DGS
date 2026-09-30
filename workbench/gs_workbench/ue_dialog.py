"""Project selection for one-action bake, plugin install, and Unreal asset import."""
from pathlib import Path
from PySide6 import QtWidgets
from . import core
from .view_camera import snapshots


def choose(parent, run):
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle("Add 4DGS Asset to Unreal")
    dialog.resize(650, 220)
    form = QtWidgets.QFormLayout(dialog)
    saved = core.STATE / "ue-settings.json"
    settings = core.read_json(saved) if saved.is_file() else {}
    project = QtWidgets.QLineEdit(settings.get("project", str(core.ROOT / "unreal/GS4DTest/GS4DTest.uproject")))
    engine = QtWidgets.QLineEdit(settings.get("engine", "C:/Program Files/Epic Games/UE_5.8"))
    row = QtWidgets.QHBoxLayout()
    row.addWidget(project)
    browse = QtWidgets.QPushButton("Browse")
    def pick():
        path, _ = QtWidgets.QFileDialog.getOpenFileName(dialog, "Choose UE 5.8 Project", project.text(), "Unreal Project (*.uproject)")
        if path:
            project.setText(path)
    browse.clicked.connect(pick)
    row.addWidget(browse)
    form.addRow("Project", row)
    form.addRow("Engine Folder", engine)
    iteration = QtWidgets.QComboBox()
    for number in snapshots(Path(run)):
        iteration.addItem(f"Iteration {number:,}", number)
    iteration.setCurrentIndex(iteration.count()-1)
    form.addRow("Snapshot", iteration)
    note = QtWidgets.QLabel("Close Unreal Editor first. Adds the local GS4D plugin and a new asset under /Game/GS4D.\nExisting assets are kept. This first player version is not yet VR-performance certified.")
    note.setWordWrap(True)
    form.addRow(note)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    export = buttons.addButton("Export and Add Asset", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
    export.setEnabled(iteration.count() > 0)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return None
    result = dict(project=project.text().strip(), engine=engine.text().strip(), iteration=iteration.currentData())
    core.write_json(saved, result)
    return result
