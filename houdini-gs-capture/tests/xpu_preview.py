"""Render a separate three-image XPU preview from the same saved fixture."""
import json
from pathlib import Path
import sys

import hou

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.13libs"))
from gs_capture_houdini import scene, worker

results = ROOT / "test-results"
original = json.loads((results / "plan.json").read_text(encoding="utf-8"))
hou.hipFile.load(original["source"]["scene"], suppress_save_prompt=True, ignore_load_warnings=True)
settings = dict(original["settings"], engine="xpu")
plan = scene.collect_plan(settings, original["source"]["source_lop"], original["source"]["targets"], require_saved=False)
worker.run(dict(plan=plan, preview=True, output=str(results / "xpu-preview"), stop_file=str(results / "xpu-stop")))
