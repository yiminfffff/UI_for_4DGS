"""Regression checks for incomplete, corrupted, mixed, and modified capture/run data."""
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_workbench import core


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original = core.read_json(core.ROOT / "maya-gs-capture/test-results/latest.json")["dataset"]
        cls.temp = tempfile.TemporaryDirectory(prefix="contracts_", dir=str(core.ROOT / "workbench/test-results"))
        cls.root = Path(cls.temp.name)
        cls.original = Path(original)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, name):
        path = self.root / name
        shutil.copytree(self.original, path)
        return path

    def test_incomplete_capture(self):
        path = self.fixture("incomplete")
        value = core.read_json(path / "capture_manifest.json"); value["status"] = "cancelled"
        core.write_json(path / "capture_manifest.json", value)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            core.validate_dataset(path)

    def test_checksum(self):
        from PIL import Image
        path = self.fixture("checksum")
        image = next((path / "images").rglob("*.png"))
        Image.new("RGB", (800, 800), "red").save(image)
        with self.assertRaisesRegex(ValueError, "checksum"):
            core.validate_dataset(path)

    def test_transform_mismatch(self):
        path = self.fixture("matrix")
        value = core.read_json(path / "transforms_train.json")
        value["frames"][0]["transform_matrix"][0][3] += 1
        core.write_json(path / "transforms_train.json", value)
        with self.assertRaisesRegex(ValueError, "manifest"):
            core.validate_dataset(path)

    def test_camera_partition_and_run_immutability(self):
        data = core.validate_dataset(self.original, stride=2)
        train = {r["camera"] for r in data["records"] if r["split"] == "train"}
        test = {r["camera"] for r in data["records"] if r["split"] == "test"}
        self.assertEqual(len(train), 14); self.assertEqual(len(test), 2); self.assertFalse(train & test)
        settings = dict(coarse=5, fine=10, checkpoint_every=5, stride=2, sh_degree=3,
                        temporal_grid=3, background="white", opacity_deformation=False)
        with self.assertRaisesRegex(ValueError, "temporal_grid"):
            core.validate_settings(dict(settings, temporal_grid=2))
        run = self.root / "new-run"
        core.create_run(run, data, settings)
        core.load_run(run)
        with self.assertRaisesRegex(ValueError, "not empty"):
            core.create_run(run, data, settings)
        prepared = core.read_json(run / "dataset/transforms_train.json")
        prepared["frames"][0]["time"] = 0.5
        core.write_json(run / "dataset/transforms_train.json", prepared)
        with self.assertRaisesRegex(ValueError, "Prepared"):
            core.load_run(run)


if __name__ == "__main__":
    unittest.main()
