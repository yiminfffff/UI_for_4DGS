"""Training/render subprocess. Uses the existing HUST environment, never the UI environment."""
import argparse
import ast
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import traceback
import types

from gs_workbench import core


def emit(kind, **payload):
    print("@WB@" + json.dumps(dict(event=kind, **payload), allow_nan=False), flush=True)


def tensor_safe(value):
    """Normalize optimizer NumPy scalars without relaxing safe checkpoint loading."""
    import numpy as np
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: tensor_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(tensor_safe(item) for item in value)
    if isinstance(value, list):
        return [tensor_safe(item) for item in value]
    return value


class Stopped(Exception):
    pass


class RunLock:
    def __init__(self, folder):
        self.path = Path(folder) / ".worker.lock"

    def __enter__(self):
        import msvcrt
        self.stream = open(self.path, "a+b")
        if self.stream.tell() == 0:
            self.stream.write(b"0"); self.stream.flush()
        self.stream.seek(0)
        try:
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.stream.close()
            raise RuntimeError("Another worker is already using this run.")
        return self

    def __exit__(self, *args):
        import msvcrt
        self.stream.seek(0)
        msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


def configure(run, config):
    from arguments import ModelParams, OptimizationParams, PipelineParams, ModelHiddenParams
    parser = argparse.ArgumentParser()
    lp, op, pp, hp = ModelParams(parser), OptimizationParams(parser), PipelineParams(parser), ModelHiddenParams(parser)
    args = parser.parse_args([])
    settings = config["settings"]
    overrides = dict(source_path=str(run / "dataset"), model_path=str(run / "model"),
                     white_background=settings["background"] == "white", eval=True,
                     coarse_iterations=settings["coarse"], iterations=settings["fine"],
                     sh_degree=settings["sh_degree"], batch_size=1, dataloader=False,
                     render_process=False, multires=[1, 2], defor_depth=0, net_width=64,
                     bounds=1.6, pruning_interval=8000, deformation_lr_final=0.0000016,
                     grid_lr_final=0.000016, no_do=not settings.get("opacity_deformation", False),
                     densify_until_iter=min(15000, max(1, settings["fine"] - 500)),
                     kplanes_config=dict(grid_dimensions=2, input_coordinate_dim=4,
                         output_coordinate_dim=32, resolution=[64, 64, 64, settings["temporal_grid"]]))
    for key, value in overrides.items():
        setattr(args, key, value)
    return args, lp.extract(args), op.extract(args), pp.extract(args), hp.extract(args)


class TrainingHooks:
    def __init__(self, run, config, resume, live=False):
        import torch
        self.run, self.config = run, config
        self.started = time.monotonic()
        self.saved = torch.load(run / "latest.pt", map_location="cuda", weights_only=True) if resume else None
        if self.saved and self.saved["fingerprint"] != config["fingerprint"]:
            raise ValueError("The checkpoint belongs to a different configuration.")
        self.last_preview = 0
        self.live = None
        if live:
            from live_render import LivePreview
            self.live = LivePreview(run, config, emit)

    def skip_stage(self, stage):
        return bool(self.saved and self.saved["stage"] == "fine" and stage == "coarse")

    def begin(self, stage, gaussians, opt, scene=None, pipe=None, background=None):
        import numpy as np
        import torch
        first = 0
        if self.saved and self.saved["stage"] == stage:
            gaussians.restore(self.saved["model"], opt)
            gaussians._deformation_accum = self.saved["deformation_accum"]
            random.setstate(self.saved["python_rng"])
            nr = self.saved["numpy_rng"]
            np.random.set_state((nr[0], np.asarray(nr[1], dtype=np.uint32), nr[2], nr[3], nr[4]))
            torch.set_rng_state(self.saved["torch_rng"].cpu())
            torch.cuda.set_rng_state_all([x.cpu() for x in self.saved["cuda_rng"]])
            first = self.saved["iteration"]
        emit("stage", stage=stage, iteration=first,
             total=self.config["settings"]["coarse" if stage == "coarse" else "fine"])
        if self.live:
            self.live.update(stage, first, gaussians, pipe, background, force=True)
        return first

    def checkpoint(self, stage, iteration, gaussians):
        import numpy as np
        import torch
        nr = np.random.get_state()
        # HUST stores the scene radius as a NumPy scalar. Convert it for safe weights-only loading.
        gaussians.spatial_lr_scale = float(gaussians.spatial_lr_scale)
        state = dict(fingerprint=self.config["fingerprint"], stage=stage, iteration=iteration,
                     model=gaussians.capture(), deformation_accum=gaussians._deformation_accum,
                     python_rng=random.getstate(), numpy_rng=(nr[0], nr[1].tolist(), nr[2], nr[3], nr[4]),
                     torch_rng=torch.get_rng_state(), cuda_rng=torch.cuda.get_rng_state_all())
        path = self.run / "latest.pt"
        temporary = path.with_suffix(".pt.tmp")
        torch.save(tensor_safe(state), temporary)
        temporary.replace(path)
        core.write_json(self.run / "checkpoint.json", dict(stage=stage, iteration=iteration))
        emit("checkpoint", stage=stage, iteration=iteration)

    def tick(self, stage, iteration, total, gaussians, scene, loss, psnr, pipe, background):
        import torch
        stop = (self.run / "stop.request").exists()
        settings = self.config["settings"]
        save = iteration % settings["checkpoint_every"] == 0 or iteration == total or stop
        payload = dict(stage=stage, iteration=iteration, total=total,
                       loss=float(loss.detach().item()), psnr=float(psnr) if math.isfinite(float(psnr)) else None,
                       points=int(gaussians.get_xyz.shape[0]), elapsed=time.monotonic() - self.started,
                       gpu_gb=round(torch.cuda.memory_allocated() / 1024**3, 2))
        if iteration % 10 == 0 or save:
            emit("progress", **payload)
            core.write_json(self.run / "status.json", dict(status="training", **payload))
        if save:
            self.checkpoint(stage, iteration, gaussians)
        if save and (stage == "fine" or stop):
            scene.save(iteration, stage)
        if self.live:
            self.live.update(stage, iteration, gaussians, pipe, background, force=iteration == total or stop)
        if stop:
            core.write_json(self.run / "status.json", dict(status="paused", **payload))
            raise Stopped("Checkpoint saved. Training paused.")

    def preview(self, stage, iteration, total, gaussians, scene, pipe, background):
        import torch
        if self.live:
            return
        if iteration == total or (self.run / "stop.request").exists() or iteration % 250 == 0:
            from gaussian_renderer import render
            from PIL import Image
            with torch.no_grad():
                cam = scene.getTestCameras()[0]
                output = render(cam, gaussians, pipe, background, stage=stage, cam_type=scene.dataset_type)["render"]
                array = (output.clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255).astype("uint8")
                path = self.run / "preview.png"
                Image.fromarray(array).save(path.with_suffix(".tmp.png"))
                path.with_suffix(".tmp.png").replace(path)
                emit("preview", path=str(path), stage=stage, iteration=iteration, before_densification=True,
                     source=next(r["image"] for r in self.config["dataset"]["records"] if r["split"] == "test"))

    def opacity_reset(self, stage, iteration):
        emit("opacity_reset", stage=stage, iteration=iteration)

    def validation(self, stage, iteration, split, l1, psnr, views):
        data = dict(stage=stage, iteration=iteration, split=split, l1=float(l1), psnr=float(psnr), views=views,
                    timing="before densification, opacity reset, and optimizer step")
        with (self.run / "validation.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(data) + "\n")
        emit("validation", **data)


def training_module(hooks):
    """Add narrow control hooks to the pinned HUST loop without editing upstream files."""
    path = core.REPO / "train.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "scene_reconstruction")
    function.body.insert(0, ast.parse("if wb.skip_stage(stage):\n    return").body[0])
    setups = [i for i, node in enumerate(function.body)
              if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
              and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "training_setup"]
    loops = [n for n in function.body if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == "iteration"]
    if len(setups) != 1 or len(loops) != 1:
        raise RuntimeError("The HUST training loop has changed. Review the workbench adapter before training.")
    background_at = next(i for i,n in enumerate(function.body) if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "background" for t in n.targets))
    function.body.insert(background_at + 1, ast.parse("first_iter = wb.begin(stage, gaussians, opt, scene, pipe, background)").body[0])
    backward = [i for i, n in enumerate(loops[0].body) if isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                and n.value.func.attr == "backward"]
    if len(backward) != 1:
        raise RuntimeError("The HUST loss update changed. Review the adapter before training.")
    loops[0].body.insert(backward[0], ast.parse(
        'if not torch.isfinite(loss).all():\n'
        '    raise RuntimeError("Training loss is not finite. The last saved checkpoint is retained; review the data and settings.")'
    ).body[0])
    loops[0].body.append(ast.parse("wb.tick(stage, iteration, final_iter, gaussians, scene, loss, psnr_, pipe, background)").body[0])
    inserted = 0
    for parent in ast.walk(function):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in list(enumerate(body)):
            if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
                continue
            call = statement.value.func
            if isinstance(call, ast.Name) and call.id == "training_report":
                body.insert(index + 1, ast.parse("wb.preview(stage, iteration, final_iter, gaussians, scene, pipe, background)").body[0])
                inserted += 1
            elif isinstance(call, ast.Attribute) and call.attr == "reset_opacity":
                body.insert(index + 1, ast.parse("wb.opacity_reset(stage, iteration)").body[0])
    if inserted != 1:
        raise RuntimeError("Could not place the preview before opacity reset. Review the training adapter.")
    report = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "training_report")
    for parent in ast.walk(report):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in list(enumerate(body)):
            if isinstance(statement, ast.Expr) and "Evaluating" in ast.unparse(statement):
                body.insert(index + 1, ast.parse("wb.validation(stage, iteration, config['name'], l1_test, psnr_test, len(config['cameras']))").body[0])
    ast.fix_missing_locations(tree)
    module = types.ModuleType("workbench_hust_train")
    module.__file__ = str(path)
    module.wb = hooks
    exec(compile(tree, str(path), "exec"), module.__dict__)
    # The desktop app communicates over stdout; no socket viewer is needed.
    module.network_gui.try_connect = lambda: None
    return module


def train(run, config, resume, live=False):
    import torch
    import numpy as np
    if core.digest(core.REPO / "train.py") != config["train_source_sha256"]:
        raise ValueError("HUST train.py changed since this run was created.")
    random.seed(6666); np.random.seed(6666); torch.manual_seed(6666); torch.cuda.manual_seed_all(6666)
    torch.cuda.set_device(0)
    hooks = TrainingHooks(run, config, resume, live)
    module = training_module(hooks)
    args, model, opt, pipeline, hidden = configure(run, config)
    module.args = args
    interval = config["settings"]["checkpoint_every"]
    test_at = sorted({opt.coarse_iterations, opt.iterations, *range(interval, opt.iterations + 1, interval)})
    module.training(model, hidden, opt, pipeline, test_at, [], [], None, -1, run.name)
    core.write_json(run / "status.json", dict(status="complete", stage="fine", iteration=opt.iterations))
    emit("complete", message="Training complete", run=str(run))


def render_result(run, config, mode, fps):
    import imageio.v2 as imageio
    import numpy as np
    from PIL import Image
    import torch
    from scene import Scene, GaussianModel
    from gaussian_renderer import render
    snapshots = [int(p.name.split("_")[-1]) for p in (run / "model/point_cloud").glob("iteration_*")
                 if p.name.split("_")[-1].isdigit() and (p / "deformation.pth").is_file()]
    if not snapshots:
        raise ValueError("No fine-stage model is available yet. Train or resume into the fine stage first.")
    args, model, opt, pipeline, hidden = configure(run, config)
    iteration = max(snapshots)
    gaussians = GaussianModel(model.sh_degree, hidden)
    with torch.no_grad():
        scene = Scene(model, gaussians, load_iteration=iteration, shuffle=False)
        sources = []
        if mode == "validation":
            records = [r for r in config["dataset"]["records"] if r["split"] == "test"]
            camera_id = records[0]["camera"]
            indices = [i for i, r in enumerate(records) if r["camera"] == camera_id]
            views = [scene.getTestCameras()[i] for i in indices]
            sources = [records[i]["image"] for i in indices]
        else:
            views = scene.getVideoCameras()
        folder = run / "renders" / (time.strftime("%Y%m%d-%H%M%S") + "-" + mode)
        folder.mkdir(parents=True, exist_ok=False)
        writer = imageio.get_writer(str(folder / "video.mp4"), fps=fps, codec="libx264", quality=8)
        frames, metrics = [], []
        bg = torch.tensor([1, 1, 1] if model.white_background else [0, 0, 0], dtype=torch.float32, device="cuda")
        try:
            for index, view in enumerate(views):
                if (run / "stop.request").exists():
                    raise Stopped("Rendering stopped. The model and training checkpoint are unchanged.")
                rgb = render(view, gaussians, pipeline, bg, cam_type=scene.dataset_type)["render"].clamp(0, 1)
                array = (rgb.permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8)
                path = folder / f"{index:05d}.png"
                Image.fromarray(array).save(path)
                writer.append_data(array)
                source = sources[index] if sources else None
                if source:
                    mse = (rgb.cpu() - view.original_image).square().mean().item()
                    metrics.append(-10 * math_log10(max(mse, 1e-12)))
                frames.append(dict(path=str(path), source=source, time=float(view.time)))
                emit("render_progress", iteration=index + 1, total=len(views), path=str(path), source=source)
        finally:
            writer.close()
        report = dict(status="complete", mode=mode, fps=fps, iteration=iteration, frames=frames,
                      video=str(folder / "video.mp4"), mean_psnr=sum(metrics) / len(metrics) if metrics else None)
        core.write_json(folder / "render.json", report)
        core.write_json(run / "latest_render.json", report)
        emit("render_complete", **report)


def math_log10(value):
    import math
    return math.log10(value)


def check_environment():
    import torch
    from diff_gaussian_rasterization import _C
    from simple_knn._C import distCUDA2
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available in the HUST environment.")
    distCUDA2(torch.rand(32, 3, device="cuda"))
    emit("environment", gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
         cuda=torch.version.cuda, vram_gb=round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check", "train", "resume", "render"])
    parser.add_argument("--run", type=Path)
    parser.add_argument("--mode", choices=["validation", "orbit"], default="validation")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--live-preview", action="store_true")
    command = parser.parse_args()
    sys.path.insert(0, str(core.REPO))
    os.chdir(core.REPO)
    if command.action == "check":
        check_environment(); return
    run = command.run.resolve()
    config = core.load_run(run)
    with RunLock(run):
        try:
            emit("status", message="Checking source images and loading the training environment…")
            current = core.validate_dataset(config["dataset"]["folder"], config["settings"]["stride"])
            if current["fingerprint"] != config["dataset"]["fingerprint"]:
                raise ValueError("Source data changed after this run was created. Create a new run.")
            import psutil
            if current["estimated_ram_gb"] > psutil.virtual_memory().available / 1024**3 * 0.85:
                raise ValueError("Not enough available RAM for this dataset. Increase temporal stride in a new run.")
            if (run / "stop.request").exists():
                raise Stopped("Stopped before training started.")
            if command.action == "render":
                if not 1 <= command.fps <= 120:
                    raise ValueError("Render FPS must be between 1 and 120.")
                render_result(run, config, command.mode, command.fps)
            else:
                train(run, config, command.action == "resume", command.live_preview)
        except Stopped as exc:
            emit("stopped", message=str(exc))
        except Exception as exc:
            if command.action != "render":
                core.write_json(run / "status.json", dict(status="failed", message=str(exc)))
            raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        emit("error", message=str(exc))
        sys.exit(1)
