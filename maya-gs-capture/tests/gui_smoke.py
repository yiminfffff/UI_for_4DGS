"""Executed by a fresh Maya GUI process, never by an existing user's session."""
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import maya.cmds as cmds
from gs_capture import dataset, maya_scene, render

OUT = ROOT / "test-results" / "interactive"
OUT.mkdir(parents=True, exist_ok=True)


def run():
    import tempfile
    run_dir = Path(tempfile.mkdtemp(prefix="render_", dir=str(OUT)))
    report = {"run": str(run_dir)}
    try:
        cmds.file(new=True, force=True)
        render.ensure_arnold()
        obj = cmds.polySphere(name="TestEffect", radius=1)[0]
        shader = cmds.shadingNode("aiStandardSurface", asShader=True, name="TestEmission")
        cmds.setAttr(shader + ".base", 0)
        cmds.setAttr(shader + ".specular", 0)
        cmds.setAttr(shader + ".emission", 1)
        cmds.setAttr(shader + ".emissionColor", 0.1, 0.45, 0.8, type="double3")
        sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="TestSG")
        cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader")
        cmds.sets(obj, edit=True, forceElement=sg)
        cmds.setKeyframe(obj, attribute="translateX", time=1, value=-0.5)
        cmds.setKeyframe(obj, attribute="translateX", time=3, value=0.5)
        targets = cmds.ls(obj, long=True)
        bounds = maya_scene.scan_bounds(targets, [1, 2, 3])
        maya_scene.create_rig(bounds)
        cmds.file(rename=str(run_dir / "scene.ma"))
        cmds.file(save=True, type="mayaAscii")
        settings = dict(start=1, end=3, step=1, test_cameras=["CAM004", "CAM012"],
                        aa_samples=2, device=0, asset_revision="gui-test", output_color="view")
        plan = maya_scene.collect_plan(settings, targets)
        plan["records"] = [plan["records"][0], plan["records"][24], plan["records"][36]]
        plan["fingerprint"] = dataset.fingerprint({k: v for k, v in plan.items() if k != "fingerprint"})
        session = dataset.OutputSession(run_dir / "preview", plan, preview=True)
        before = {attr: cmds.getAttr(attr) for attr in (
            "defaultRenderGlobals.imageFilePrefix", "defaultRenderGlobals.currentRenderer",
            "defaultResolution.width", "defaultResolution.height", "defaultArnoldDriver.aiTranslator",
            "defaultArnoldDriver.pngUnpremultAlpha", "defaultArnoldRenderOptions.AASamples")}
        for record in plan["records"]:
            render.render_one(session, record)
        session.finish()
        assert all((cmds.getAttr(a) or "") == (value or "") for a, value in before.items()), "Settings restoration failed"
        from PySide6 import QtWidgets
        from gs_capture.ui import CapturePanel
        panel = CapturePanel()
        panel.targets = targets
        panel.target_label.setText("TestEffect")
        panel.cached.setChecked(True)
        panel.output.setText(str(session.root))
        panel.start.setValue(1); panel.end.setValue(3)
        panel.show(); QtWidgets.QApplication.processEvents()
        panel.grab().save(str(OUT / "panel-in-maya.png"))
        report.update(status="passed", images=[str(session.path(r)) for r in plan["records"]],
                      settings_restored=True, maya=cmds.about(version=True),
                      mtoa=cmds.pluginInfo("mtoa", query=True, version=True))
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
        traceback.print_exc()
    finally:
        dataset.write_json(OUT / "result.json", report)
        cmds.quit(force=True)


cmds.evalDeferred(run, lowestPriority=True)
