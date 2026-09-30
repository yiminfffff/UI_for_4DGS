"""Resident CUDA renderer over private stdin/stdout pipes; no network listener."""
import argparse
import base64
import io
import json
from pathlib import Path
import sys
import time
import traceback

from gs_workbench import core
from gs_workbench.view_camera import snapshots
from worker import configure, RunLock


def emit(event, **data):
    print("@VIEW@" + json.dumps(dict(event=event, **data), allow_nan=False), flush=True)


class ModelViewer:
    def __init__(self, run, iteration=None, stage="fine"):
        sys.path.insert(0, str(core.REPO))
        import torch
        from scene.gaussian_model import GaussianModel
        self.run = Path(run)
        self.config = core.load_run(run)
        self.stage = stage
        available = snapshots(self.run, stage)
        self.iteration = iteration or max(available, default=0)
        if self.iteration not in available:
            raise ValueError(f"The requested {stage}-stage snapshot is not available.")
        _, model, _, self.pipe, hidden = configure(self.run, self.config)
        self.gaussians = GaussianModel(model.sh_degree, hidden)
        prefix = "coarse_iteration" if stage == "coarse" else "iteration"
        folder = self.run / f"model/point_cloud/{prefix}_{self.iteration}"
        self.gaussians.load_ply(str(folder / "point_cloud.ply"))
        self.gaussians.load_model(str(folder))
        self.gaussians._deformation.eval()
        self.background = torch.tensor([1, 1, 1] if model.white_background else [0, 0, 0], dtype=torch.float32, device="cuda")

    def render(self, request):
        from live_render import render_camera
        return render_camera(self.gaussians, self.pipe, self.background, request,
            self.config["dataset"]["camera_angle_x"], self.stage)


def main():
    from PIL import Image
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--iteration", type=int)
    parser.add_argument("--stage", choices=["coarse","fine"], default="fine")
    args = parser.parse_args()
    with RunLock(args.run):
        model = ModelViewer(args.run, args.iteration, args.stage)
        emit("ready", iteration=model.iteration, points=len(model.gaussians.get_xyz))
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("action") == "close":
                return
            start = time.perf_counter()
            pixels = model.render(request)
            data = io.BytesIO()
            Image.fromarray(pixels).save(data, format="JPEG", quality=92)
            emit("frame", id=request.get("id"), time=request["time"],
                 milliseconds=round(1000 * (time.perf_counter() - start), 2),
                 image=base64.b64encode(data.getvalue()).decode("ascii"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        emit("error", message=str(exc))
        sys.exit(1)
