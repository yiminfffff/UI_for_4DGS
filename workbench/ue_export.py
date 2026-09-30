"""Bake HUST deformation to an independently specified UE Gaussian sequence."""
import argparse
import json
from pathlib import Path
import struct
import sys
import time

from gs_workbench import core
from gs_workbench.view_camera import duration
from viewer_worker import ModelViewer
from worker import RunLock


def bake(run, output, iteration=None, progress=None):
    import torch
    import numpy as np
    output = Path(output)
    if output.exists():
        raise ValueError("The export file already exists. Choose a new asset name.")
    with RunLock(run), torch.inference_mode():
        model = ModelViewer(run, iteration)
        from utils.general_utils import build_rotation
        config, native = model.config, model.gaussians
        times = sorted({float(r["time"]) for r in config["dataset"]["records"]})
        count = len(native.get_xyz)
        expected_size = 32 + 4*len(times) + count*len(times)*58*4
        if count > 500000 or expected_size > 1_500_000_000:
            raise ValueError("This sequence exceeds the first version's 1.5 GB asset limit. Use a smaller training capture.")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".gs4d.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(struct.pack("<8sIIIIff", b"GS4D001\0", 1, count, len(times), native.active_sh_degree,
                                         float(config["dataset"].get("fps", 24)), duration(config)))
                stream.write(np.asarray(times, dtype="<f4").tobytes())
                axis = torch.tensor([1, -1, 1], device="cuda", dtype=torch.float32)
                for index, timestamp in enumerate(times):
                    t = torch.full((count, 1), timestamp, device="cuda")
                    xyz, scales, rotation, opacity, sh = native._deformation(native.get_xyz, native._scaling,
                        native._rotation, native._opacity, native.get_features, t)
                    r = build_rotation(rotation)
                    cov = (r * scales.exp().square().unsqueeze(1)) @ r.transpose(1, 2)
                    cov = cov * axis[None, :, None] * axis[None, None, :] * 10000
                    packed = torch.zeros((count, 58), dtype=torch.float32, device="cuda")
                    packed[:, :3] = xyz * axis * 100
                    packed[:, 3:9] = cov[:, [0, 0, 0, 1, 1, 2], [0, 1, 2, 1, 2, 2]]
                    packed[:, 9:10] = opacity.sigmoid()
                    packed[:, 10:10+sh.shape[1]*3] = sh.reshape(count, -1)
                    if not torch.isfinite(packed).all():
                        raise ValueError("The model contains non-finite Gaussian attributes.")
                    stream.write(packed.cpu().numpy().astype("<f4", copy=False).tobytes())
                    if progress:
                        progress(index+1, len(times))
            if temporary.stat().st_size != expected_size:
                raise ValueError("The export size does not match its header.")
            temporary.replace(output)
        finally:
            if temporary.exists():
                temporary.unlink()
        metadata = dict(format="GS4D001", run=str(run), iteration=model.iteration, points=count, frames=len(times),
                        duration_seconds=duration(config), centimeters_per_normalized_unit=100,
                        coordinates="UE XYZ = normalized HUST (X, -Y, Z) * 100", sh_basis="HUST world directions",
                        bytes=expected_size, sha256=core.digest(output), source_fingerprint=config["fingerprint"])
        core.write_json(output.with_suffix(".json"), metadata)
        return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iteration", type=int)
    args = parser.parse_args()
    result = bake(args.run.resolve(), args.output.resolve(), args.iteration,
                  lambda current, total: print("@UE@" + json.dumps(dict(event="progress", current=current, total=total)), flush=True))
    print("@UE@" + json.dumps(dict(event="baked", **result)), flush=True)
