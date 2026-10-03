"""Run with Houdini 22 hython to exercise the actual Solaris/Karma pipeline."""
import json
from pathlib import Path
import sys

import hou

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.13libs"))
from gs_capture_houdini import dataset, scene

folder = ROOT / "test-results"
folder.mkdir(exist_ok=True)
source = hou.node("/stage").createNode("pythonscript", "animated_effect")
source.parm("python").set('''from pxr import UsdGeom, UsdLux, Gf
stage = hou.pwd().editableStage()
sphere = UsdGeom.Sphere.Define(stage, '/World/Effect')
sphere.CreateRadiusAttr(0.65 + (hou.frame() - 1) * 0.15)
sphere.CreateDisplayColorAttr([(0.55, 0.08, 0.025)])
sphere.AddTranslateOp().Set(Gf.Vec3d((hou.frame() - 1) * 0.3, 0, 0))
light = UsdLux.DomeLight.Define(stage, '/World/Light')
light.CreateIntensityAttr(1.0)
''')
hou.setFrame(1)
hou.playbar.setPlaybackRange(1, 2)
targets = ["/World/Effect"]
bounds = scene.scan_bounds(source, targets, [1, 2])
rig = scene.create_rig(source, bounds)
hou.hipFile.save(str(folder / "fixture.hipnc"))
ocio_path, ocio = scene.color_config()
settings = dict(start=1, end=2, step=1, test_cameras=["CAM004", "CAM012"],
                engine="cpu", samples=4, asset_revision="fixture-v1",
                display="sRGB - Display", view="ACES 1.0 - SDR Video")
plan = scene.collect_plan(settings, source.path(), targets, require_saved=False)
dataset.write_json(folder / "plan.json", plan)
dataset.write_json(folder / "preview-job.json", dict(plan=plan, preview=True,
    output=str(folder / "preview"), stop_file=str(folder / "stop-request")))
dataset.write_json(folder / "full-job.json", dict(plan=plan, preview=False,
    output=str(folder / "capture"), stop_file=str(folder / "stop-request")))
print("FIXTURE_READY", plan["fingerprint"], flush=True)
