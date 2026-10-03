"""Run from Houdini's Python Shell with runpy.run_path to install the shelf."""
import json
from pathlib import Path
import sys


def install():
    import hou
    root = Path(__file__).resolve().parent
    if hou.applicationVersion()[:2] != (22, 0):
        raise RuntimeError("This plugin is designed for Houdini 22.0 with Python 3.13.")
    package = Path(hou.getenv("HOUDINI_USER_PREF_DIR")) / "packages/gs_capture_houdini.json"
    package.parent.mkdir(parents=True, exist_ok=True)
    value = {"enable": True, "path": root.as_posix()}
    temporary = package.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(package)
    scripts = str(root / "python3.13libs")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    if hou.isUIAvailable():
        hou.shelves.loadFile(str(root / "toolbar/GSCapture.shelf"))
        shelf = hou.shelves.shelves()["gs_capture_houdini"]
        sets = hou.ui.curDesktop().shelfDock().shelfSets()
        if sets:
            shelf_set = sets[0]
            if shelf not in shelf_set.shelves():
                shelf_set.setShelves(shelf_set.shelves() + (shelf,))
        import gs_capture_houdini
        gs_capture_houdini.show()
    print("Render for 4DGS installed: " + str(package))
    return package


if __name__ == "__main__":
    install()
