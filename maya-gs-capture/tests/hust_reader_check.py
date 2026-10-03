"""Run with the existing HUST environment after maya_integration.py."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "HUST-Windows"))
from scene.dataset_readers import read_timeline, readCamerasFromTransforms

latest = json.loads((root / "maya-gs-capture/test-results/latest.json").read_text(encoding="utf-8"))
path = latest["dataset"]
timeline, maximum = read_timeline(path)
train = readCamerasFromTransforms(path, "transforms_train.json", True, mapper=timeline)
test = readCamerasFromTransforms(path, "transforms_test.json", True, mapper=timeline)
assert len(train) == 28 and len(test) == 4
assert maximum == 1.0 and set(timeline) == {0.0, 1.0}
assert all(tuple(c.image.shape) == (3, 800, 800) for c in train + test)
report = dict(status="passed", train_views=len(train), test_views=len(test),
              image_shape=[3, 800, 800], times=list(timeline), dataset=path)
(root / "maya-gs-capture/test-results/hust-reader.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
