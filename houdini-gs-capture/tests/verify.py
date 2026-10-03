"""Numerical camera, alpha, integrity, and resume checks using the rendered fixture."""
import copy
import json
from pathlib import Path
import sys
import unittest

import hou
import numpy as np
import OpenImageIO as oiio
import PyOpenColorIO as ocio
from pxr import Gf, UsdGeom

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.13libs"))
from gs_capture_houdini import dataset, render, scene, worker

RESULTS = ROOT / "test-results"
PLAN = json.loads((RESULTS / "plan.json").read_text(encoding="utf-8"))


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hou.hipFile.load(PLAN["source"]["scene"], suppress_save_prompt=True, ignore_load_warnings=True)

    def test_projection_matches_usd(self):
        center, scale = PLAN["normalization"]["center"], PLAN["normalization"]["scale"]
        conversion = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
        stage = scene.get_stage(hou.node(PLAN["source"]["rig_lop"]))
        point = np.array([0.21, 0.14, -0.13])
        normalized = conversion @ ((point - center) * scale)
        for camera in PLAN["cameras"]:
            usd_camera = UsdGeom.Camera(stage.GetPrimAtPath(camera["prim_path"]))
            matrix = np.array(usd_camera.ComputeLocalToWorldTransform(hou.frame())).T
            original = np.linalg.inv(matrix) @ np.append(point, 1)
            exported = np.array(dataset.export_pose(camera["world_matrix"], center, scale))
            result = np.linalg.inv(exported) @ np.append(normalized, 1)
            np.testing.assert_allclose(original[:2] / -original[2], result[:2] / -result[2], atol=1e-7)
            self.assertLess(result[2], 0)
            direction = -matrix[:3, 2]
            toward = np.array(center) - matrix[:3, 3]
            np.testing.assert_allclose(direction, toward / np.linalg.norm(toward), atol=1e-6)

    def test_animated_camera_rejected(self):
        camera = hou.node(PLAN["source"]["rig_lop"] + "/CAM001")
        parm = camera.parm("tx")
        old = parm.eval()
        try:
            parm.setExpression(f"{old} + $F * 0.1", hou.exprLanguage.Hscript)
            with self.assertRaisesRegex(ValueError, "changes"):
                scene.collect_plan(PLAN["settings"], PLAN["source"]["source_lop"], PLAN["source"]["targets"], require_saved=False)
        finally:
            parm.deleteAllKeyframes()
            parm.set(old)

    def test_straight_alpha_color_conversion(self):
        pixels = np.empty((800, 800, 4), dtype=np.float32)
        pixels[:] = [0.2 * 0.25, 0.4 * 0.25, 0.6 * 0.25, 0.25]
        image = oiio.ImageBuf(oiio.ImageSpec(800, 800, 4, oiio.FLOAT))
        image.set_pixels(oiio.ROI.All, pixels)
        self.assertTrue(image.write(str(RESULTS / "synthetic-alpha.exr")))
        render.convert_image(RESULTS / "synthetic-alpha.exr", RESULTS / "synthetic-alpha.png", PLAN)
        config = ocio.Config.CreateFromFile(PLAN["source"]["ocio_config"])
        transform = ocio.DisplayViewTransform(src=PLAN["source"]["scene_linear"],
            display=PLAN["source"]["color_display"], view=PLAN["source"]["color_view"])
        expected = config.getProcessor(transform).getDefaultCPUProcessor().applyRGB([0.2, 0.4, 0.6])
        options = oiio.ImageSpec()
        options.attribute("oiio:UnassociatedAlpha", 1)
        inp = oiio.ImageInput.open(str(RESULTS / "synthetic-alpha.png"), options)
        actual = np.asarray(inp.read_image(format=oiio.FLOAT))[400, 400]
        inp.close()
        np.testing.assert_allclose(actual, expected + [0.25], atol=1.5 / 255)

    def test_preview_is_not_training_dataset(self):
        root = RESULTS / "preview"
        manifest = json.loads((root / "capture_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "preview_complete")
        self.assertEqual(len(manifest["completed"]), 3)
        self.assertFalse((root / "transforms_train.json").exists())

    def test_resume_and_tamper(self):
        root = RESULTS / "capture"
        session = dataset.OutputSession(root, PLAN)
        self.assertTrue(all(session.done(r) for r in PLAN["records"]))
        self.assertFalse((root / "transforms_train.json").exists())
        record = PLAN["records"][0]
        path = session.path(record)
        original = path.read_bytes()
        try:
            path.write_bytes(b"damaged PNG")
            self.assertFalse(session.done(record))
            with self.assertRaisesRegex(RuntimeError, "missing or damaged"):
                session.finish()
        finally:
            path.write_bytes(original)
            session.finish()
        modified = copy.deepcopy(PLAN)
        modified["fingerprint"] = "different"
        with self.assertRaisesRegex(ValueError, "different scene"):
            dataset.OutputSession(root, modified)

    def test_source_hip_unchanged(self):
        self.assertEqual(dataset.digest_file(PLAN["source"]["scene"]), PLAN["source"]["scene_sha256"])

    def test_small_effect_not_clipped(self):
        network = hou.node("/stage").createNode("subnet", "small_effect_test")
        try:
            source = network.createNode("pythonscript", "effect")
            source.parm("python").set("from pxr import UsdGeom\nUsdGeom.Sphere.Define(hou.pwd().editableStage(), '/Effect').CreateRadiusAttr(0.0001)")
            bounds = scene.scan_bounds(source, ["/Effect"], [1, 2])
            rig = scene.create_rig(source, bounds)
            stage = scene.get_stage(rig)
            for index in range(1, 17):
                camera = UsdGeom.Camera(stage.GetPrimAtPath(f"/GSCapture/CAM{index:03d}"))
                local = camera.ComputeLocalToWorldTransform(1).GetInverse().Transform(Gf.Vec3d(0))
                near, far = camera.GetClippingRangeAttr().Get(1)
                self.assertLess(near, -local[2] - 0.0001)
                self.assertGreater(far, -local[2] + 0.0001)
        finally:
            network.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
