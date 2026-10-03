"""Exercise the real resident CUDA viewer and verify camera response."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import base64
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_workbench import core
from gs_workbench.view_camera import orbit_pose
from PIL import Image

run = core.ROOT / "workbench-runs/capture-0919-203240"
out = core.ROOT / "workbench/test-results/live-viewer"
out.mkdir(parents=True, exist_ok=True)
process = subprocess.Popen([str(core.PYTHON), str(core.ROOT / "workbench/viewer_worker.py"), "--run", str(run)],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=core.environment(),
    text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)


def receive(event):
    for line in process.stdout:
        if "@VIEW@" in line:
            data = json.loads(line.split("@VIEW@", 1)[1])
            if data["event"] == "error":
                raise RuntimeError(data["message"])
            if data["event"] == event:
                return data
    raise RuntimeError("Viewer stopped without a response.")


try:
    ready = receive("ready")
    samples = []
    for index in range(4):
        pose = orbit_pose([0, 0, 0], index * 0.3, 0.4, 4)
        request = dict(id=index, time=index / 3, pose=pose, size=512)
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        response = receive("frame")
        pixels = base64.b64decode(response.pop("image"))
        assert Image.open(io.BytesIO(pixels)).size == (512, 512)
        (out / f"view-{index}.jpg").write_bytes(pixels)
        samples.append(response)
    assert (out / "view-0.jpg").read_bytes() != (out / "view-3.jpg").read_bytes()
    process.stdin.write('{"action":"close"}\n')
    process.stdin.flush()
    assert process.wait(timeout=15) == 0
    core.write_json(out / "report.json", dict(ready=ready, frames=samples))
    print(json.dumps(dict(ready=ready, frames=samples)), flush=True)
finally:
    if process.poll() is None:
        process.kill()
