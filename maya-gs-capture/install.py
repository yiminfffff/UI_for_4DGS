"""Drag this file into a Maya viewport. Adds a shelf button; no package install."""
from pathlib import Path
import sys


def install():
    import maya.cmds as cmds
    import maya.mel as mel
    root = Path(__file__).resolve().parent
    scripts = str(root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    command = ("import sys\n"
               f"p = {scripts!r}\n"
               "if p not in sys.path: sys.path.insert(0, p)\n"
               "import gs_capture\ngs_capture.show()\n")
    shelf = "GSCapture"
    if not cmds.shelfLayout(shelf, exists=True):
        top = mel.eval("$gsCaptureShelf = $gShelfTopLevel")
        cmds.shelfLayout(shelf, parent=top)
    for child in cmds.shelfLayout(shelf, query=True, childArray=True) or []:
        if cmds.objectTypeUI(child) == "shelfButton" and cmds.shelfButton(child, query=True, annotation=True) == "GS Capture for Maya 2027":
            cmds.deleteUI(child)
    cmds.shelfButton(parent=shelf, label="GS Capture", annotation="GS Capture for Maya 2027",
                     image="render_camera.png", imageOverlayLabel="GS", sourceType="python", command=command)
    mel.eval("saveAllShelves $gShelfTopLevel;")
    import gs_capture
    gs_capture.show()


def onMayaDroppedPythonFile(*args):
    install()


if __name__ == "__main__":
    install()
