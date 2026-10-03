"""Camera validation and native rendering shared by live and saved-model previews."""
import math
import numpy as np
import torch


def render_camera(gaussians, pipe, background, request, default_fov, stage="fine"):
    from scene.cameras import MiniCam
    from utils.graphics_utils import getProjectionMatrix
    from gaussian_renderer import render
    pose = np.asarray(request["pose"], dtype=np.float32)
    size, timestamp = int(request.get("size", 512)), float(request["time"])
    fov = float(request.get("fov", default_fov))
    if (pose.shape != (4, 4) or not np.isfinite(pose).all() or not 128 <= size <= 1280
            or not 0 <= timestamp <= 1 or not 0.05 < fov < math.pi - 0.05):
        raise ValueError("Invalid viewer camera request.")
    cv = pose.copy()
    cv[:3, 1:3] *= -1
    view = torch.tensor(np.linalg.inv(cv).T, device="cuda")
    projection = getProjectionMatrix(0.01, 1000, fov, fov).T.cuda()
    camera = MiniCam(size, size, fov, fov, 0.01, 1000, view, view @ projection, timestamp)
    with torch.no_grad():
        image = render(camera, gaussians, pipe, background, stage=stage)["render"]
        return (image.clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255).astype("uint8")


class LivePreview:
    def __init__(self, run, config, emit):
        self.path = run / "live-camera.json"
        self.config, self.emit = config, emit
        self.last_id = None
        self.next_frame = 0
        self.render_cost = 0

    def update(self, stage, iteration, gaussians, pipe, background, force=False):
        import base64
        import io
        import json
        import time
        from PIL import Image
        now = time.monotonic()
        if not self.path.is_file() or (not force and now < self.next_frame):
            return
        try:
            request = json.loads(self.path.read_text(encoding="utf-8"))
            changed = request.get("id") != self.last_id
            if not force and not changed and now < getattr(self, "next_idle", 0):
                return
            start = time.monotonic()
            pixels = render_camera(gaussians, pipe, background, request,
                self.config["dataset"]["camera_angle_x"], stage)
            data = io.BytesIO()
            Image.fromarray(pixels).save(data, format="JPEG", quality=90)
            self.render_cost = time.monotonic() - start
            self.last_id = request.get("id")
            self.emit("live_frame", id=self.last_id, time=request["time"], stage=stage,
                iteration=iteration, milliseconds=round(self.render_cost*1000, 1),
                image=base64.b64encode(data.getvalue()).decode("ascii"))
        except Exception as exc:
            # Preview errors must not discard an otherwise valid training iteration.
            self.emit("live_error", message="Live preview: " + str(exc))
        finally:
            self.next_frame = time.monotonic() + max(0.15, self.render_cost * 9)
            self.next_idle = time.monotonic() + 1.5
