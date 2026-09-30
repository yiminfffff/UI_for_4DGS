"""Validate installed training code, dependencies and an actual tiny CUDA render."""
import json
from pathlib import Path
import sys
import traceback
from gs_workbench import core


def check():
    sys.path.insert(0,str(core.REPO))
    import torch
    from worker import check_environment
    check_environment()
    from scene.gaussian_model import GaussianModel
    from arguments import ModelHiddenParams
    from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer
    from simple_knn._C import distCUDA2
    import argparse
    parser = argparse.ArgumentParser(); hidden = ModelHiddenParams(parser).extract(parser.parse_args([]))
    model = GaussianModel(3,hidden)
    assert model._deformation is not None
    for name in ("train.py", "gaussian_renderer/__init__.py", "scene/gaussian_model.py"):
        if not (core.REPO/name).is_file(): raise RuntimeError("Missing HUST source: "+name)
    settings = GaussianRasterizationSettings(image_height=64,image_width=64,tanfovx=1,tanfovy=1,
        bg=torch.zeros(3,device="cuda"),scale_modifier=1.0,viewmatrix=torch.eye(4,device="cuda"),
        projmatrix=torch.eye(4,device="cuda"),sh_degree=0,campos=torch.zeros(3,device="cuda"),prefiltered=False,debug=False)
    points = torch.tensor([[0.,0.,2.]],device="cuda")
    image = GaussianRasterizer(settings)(means3D=points,means2D=torch.zeros_like(points),shs=None,
        colors_precomp=torch.ones_like(points),opacities=torch.ones(1,1,device="cuda")*.8,
        scales=torch.ones_like(points)*.1,rotations=torch.tensor([[1.,0.,0.,0.]],device="cuda"),cov3D_precomp=None)[0]
    assert torch.isfinite(image).all() and image.max()>0, "CUDA rasterization did not produce a valid image"
    print("@MAINT@"+json.dumps(dict(status="Ready",message="HUST source, deformation network, CUDA extensions and test render passed.",
        torch=torch.__version__,cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(0),source_sha256=core.digest(core.REPO/"train.py"))),flush=True)


if __name__ == "__main__":
    try: check()
    except Exception:
        print("@MAINT@"+json.dumps(dict(status="Needs Repair",message=traceback.format_exc())),flush=True)
        sys.exit(1)
