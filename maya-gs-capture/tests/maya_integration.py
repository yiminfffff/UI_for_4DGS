"""Run with Maya 2027 mayapy. Creates only isolated test scenes and outputs."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import maya.standalone
maya.standalone.initialize(name="python")
import maya.cmds as cmds
import maya.api.OpenMaya as om
from PySide6 import QtWidgets, QtGui
from gs_capture import dataset, maya_scene, render

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
OUT = ROOT / "test-results"
OUT.mkdir(exist_ok=True)
RUN = Path(tempfile.mkdtemp(prefix="run_", dir=str(OUT)))
results = []


def passed(name):
    results.append(name)
    print("PASS:", name, flush=True)


def expect_error(action):
    try:
        action()
    except (ValueError, RuntimeError):
        return
    raise AssertionError("Expected validation failure")


def main():
    render.ensure_arnold()
    cmds.file(new=True, force=True)
    render.ensure_arnold()
    obj = cmds.polyCube(name="Effect", width=2, height=2, depth=2)[0]
    cmds.setKeyframe(obj, attribute="translateX", time=1001, value=-1)
    cmds.setKeyframe(obj, attribute="translateX", time=1003, value=1)
    targets = cmds.ls(obj, long=True)
    frames = dataset.frames_for(1001, 1003, 2)
    cmds.currentTime(1002)
    bounds = maya_scene.scan_bounds(targets, frames)
    assert bounds == [-2, -1, -1, 2, 1, 1], bounds
    assert cmds.currentTime(query=True) == 1002
    passed("animation union bounds and timeline restoration")
    shapes = maya_scene.create_rig(bounds)
    assert len(shapes) == 16
    ids = [cmds.getAttr(s + ".gsCameraId") for s in shapes]
    assert ids == [f"CAM{i:03d}" for i in range(1, 17)]
    passed("16 fixed cameras and stable IDs")
    infos = [maya_scene.camera_info(s) for s in shapes]
    # Maya's inch/mm conversion uses a slightly different constant internally.
    assert abs(infos[0]["camera_angle_x"] - 2 * math.atan(36 / 70)) < 1e-5
    center, scale = dataset.normalization(bounds)
    for info in infos:
        m = om.MMatrix(info["world_matrix"])
        pose = dataset.export_pose(info["world_matrix"], center, scale)
        exported = om.MMatrix([pose[row][col] for col in range(4) for row in range(4)])
        for p in [(0.3, 0.2, -0.4), (-1, 0.5, 0.5), (1, -0.5, -0.5)]:
            camera_p = om.MPoint(*p) * m.inverse()
            normalized = [(p[i] - center[i]) * scale for i in range(3)]
            exported_p = om.MPoint(normalized[0], -normalized[2], normalized[1]) * exported.inverse()
            for axis in (0, 1):
                assert abs(camera_p[axis] / -camera_p.z - exported_p[axis] / -exported_p.z) < 1e-7
        camera_center = om.MPoint(*center) * m.inverse()
        assert abs(camera_center.x) < 1e-6 and abs(camera_center.y) < 1e-6 and camera_center.z < 0
    passed("Maya-to-HUST projection equivalence across all 16 cameras")
    settings = dict(start=1001, end=1003, step=2, test_cameras=["CAM004", "CAM012"],
                    aa_samples=1, device=0, asset_revision="test", output_color="view")
    cmds.file(rename=str(RUN / "fixture.ma")); cmds.file(save=True, type="mayaAscii")
    plan = maya_scene.collect_plan(settings, targets)
    assert len(plan["records"]) == 32
    assert {r["time"] for r in plan["records"]} == {0, 1}
    assert [r["maya_frame"] for r in plan["records"] if r["camera"] == "CAM001"] == [1001, 1003]
    passed("saved-scene preflight, time normalization, frame mapping")
    session = dataset.OutputSession(RUN / "dataset", plan)
    image = QtGui.QImage(800, 800, QtGui.QImage.Format.Format_RGBA8888)
    image.fill(QtGui.QColor(70, 150, 200, 180))
    for record in plan["records"]:
        path = RUN / "temporary.png"; image.save(str(path)); session.commit(record, path)
    session.finish()
    training = json.loads((session.root / "transforms_train.json").read_text())
    testing = json.loads((session.root / "transforms_test.json").read_text())
    assert len(training["frames"]) == 28 and len(testing["frames"]) == 4
    assert not {r["file_path"] for r in training["frames"]} & {r["file_path"] for r in testing["frames"]}
    assert all(not r["file_path"].endswith(".png") and "\\" not in r["file_path"] for r in training["frames"])
    passed("decode PNG, dataset export, disjoint camera splits, relative paths")
    resumed = dataset.OutputSession(session.root, plan)
    assert resumed.done(plan["records"][0])
    corrupt = resumed.path(plan["records"][0]); corrupt.write_bytes(b"broken PNG")
    assert not resumed.done(plan["records"][0])
    assert not (resumed.root / "transforms_train.json").exists()
    expect_error(resumed.finish)
    path = RUN / "temporary.png"; image.save(str(path)); resumed.commit(plan["records"][0], path)
    resumed.finish()
    changed = dict(plan, fingerprint="different")
    expect_error(lambda: dataset.OutputSession(session.root, changed))
    passed("resume verification, corrupt-image rejection, stale-manifest rejection")
    attr = "defaultRenderGlobals.imageFilePrefix"
    before = cmds.getAttr(attr)
    try:
        with render.temporary_settings({attr: "temporary", "missingNode.missingAttr": 1}):
            pass
    except RuntimeError:
        pass
    assert (cmds.getAttr(attr) or "") == (before or "")
    try:
        with render.temporary_settings({attr: "temporary"}):
            cmds.currentTime(1001)
            raise RuntimeError("simulated renderer failure")
    except RuntimeError:
        pass
    assert (cmds.getAttr(attr) or "") == (before or "") and cmds.currentTime(query=True) == 1002
    passed("render override rollback on setup and rendering exceptions")
    transform = cmds.listRelatives(shapes[0], parent=True, fullPath=True)[0]
    cmds.setKeyframe(transform, attribute="translateX", time=1001)
    cmds.setKeyframe(transform, attribute="translateX", time=1003, value=20)
    cmds.file(save=True, type="mayaAscii")
    expect_error(lambda: maya_scene.collect_plan(settings, targets))
    passed("animated-camera rejection")
    # Maya standalone owns a QCoreApplication, so QWidget tests belong to gui_smoke.py.
    dataset.write_json(OUT / "latest.json", dict(passed=results, run=str(RUN), dataset=str(session.root)))


try:
    main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
finally:
    maya.standalone.uninitialize()
