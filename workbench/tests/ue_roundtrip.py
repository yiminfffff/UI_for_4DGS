"""Render decoded UE attributes with CUDA and compare against the neural model."""
import json
import math
from pathlib import Path
import struct
import sys
import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from viewer_worker import ModelViewer
from gs_workbench import core

model = ModelViewer(core.RUNS / "capture-0919-203240")
from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer
from utils.graphics_utils import getProjectionMatrix
file = core.ROOT / "unreal/exports/capture_0919.gs4d"
with file.open("rb") as stream:
    magic, version, count, frames, degree, fps, duration = struct.unpack("<8sIIIIff", stream.read(32))
assert magic == b"GS4D001\0" and version == 1
times = np.memmap(file, dtype="<f4", mode="r", offset=32, shape=(frames,))
data = np.memmap(file, dtype="<f4", mode="r", offset=32+4*frames, shape=(frames,count,58))
record = next(r for r in model.config["dataset"]["records"] if r["camera"] == "CAM004")
pose = np.array(record["transform_matrix"], dtype=np.float32)
cv = pose.copy(); cv[:3,1:3] *= -1
view = torch.tensor(np.linalg.inv(cv).T, device="cuda")
fov = model.config["dataset"]["camera_angle_x"]
projection = getProjectionMatrix(0.01, 1000, fov, fov).T.cuda()
settings = GaussianRasterizationSettings(image_height=320, image_width=320,
    tanfovx=math.tan(fov/2), tanfovy=math.tan(fov/2), bg=model.background,
    scale_modifier=1.0, viewmatrix=view, projmatrix=view@projection, sh_degree=degree,
    campos=torch.tensor(pose[:3,3], device="cuda"), prefiltered=False, debug=False)
renderer = GaussianRasterizer(raster_settings=settings)
results = []
with torch.inference_mode():
    for index in (0, frames//2, frames-1):
        p = torch.tensor(np.array(data[index]), device="cuda")
        xyz = p[:,:3] * torch.tensor([1,-1,1], device="cuda") / 100
        cov = p[:,3:9] * torch.tensor([1,-1,1,1,-1,1], device="cuda") / 10000
        rgb = renderer(means3D=xyz.contiguous(), means2D=torch.zeros_like(xyz),
            shs=p[:,10:].reshape(count,16,3).contiguous(), colors_precomp=None,
            opacities=p[:,9:10].contiguous(), scales=None, rotations=None,
            cov3D_precomp=cov.contiguous())[0]
        decoded = (rgb.clamp(0,1).permute(1,2,0).cpu().numpy()*255).astype("uint8")
        native = model.render(dict(pose=pose.tolist(),time=float(times[index]),size=320))
        error = np.abs(decoded.astype(float)-native.astype(float))
        results.append(dict(frame=index, mean_absolute_byte_error=float(error.mean()), max_byte_error=float(error.max())))
        assert error.mean() < 0.1, results[-1]
core.write_json(core.ROOT / "workbench/test-results/ue-roundtrip.json",dict(status="passed",samples=results))
print(json.dumps(results))
