"""Bake a completed workbench model and verify PLY playback with held-out views.

This diagnostic keeps HUST coordinates and does not certify an Unreal importer.
Run with the HUST environment and pass --run and a new --output directory.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys
import time

from gs_workbench import core
from worker import RunLock, configure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    run, output = options.run.resolve(), options.output.resolve()
    config = core.load_run(run)
    if core.read_json(run / "status.json").get("status") != "complete":
        raise ValueError("This diagnostic requires a completed training run.")
    if output.exists():
        raise ValueError("Choose a new output folder; existing results are never overwritten.")
    if output == run or output in run.parents or output == Path(config["dataset"]["folder"]):
        raise ValueError("Keep diagnostic outputs separate from training and source files.")
    sys.path.insert(0, str(core.REPO))
    import numpy as np
    import torch
    from PIL import Image, ImageDraw, ImageFont
    import imageio.v2 as imageio
    from scene.gaussian_model import GaussianModel
    from scene.dataset_readers import readCamerasFromTransforms, read_timeline
    from scene.dataset import FourDGSdataset
    from gaussian_renderer import render
    from utils.loss_utils import ssim

    with RunLock(run), torch.no_grad():
        print("Checking all source images and saved configuration...", flush=True)
        current = core.validate_dataset(config["dataset"]["folder"], config["settings"]["stride"])
        if current["fingerprint"] != config["dataset"]["fingerprint"]:
            raise ValueError("Source dataset changed since training.")
        snapshots = [p for p in (run / "model/point_cloud").glob("iteration_*")
                     if p.name.split("_")[-1].isdigit() and (p / "deformation.pth").is_file()]
        snapshot = max(snapshots, key=lambda p: int(p.name.split("_")[-1]))
        iteration = int(snapshot.name.split("_")[-1])
        if iteration != config["settings"]["fine"]:
            raise ValueError("The final model snapshot is missing.")
        protected = [run / "run.json", run / "status.json", run / "latest.pt", *snapshot.glob("*")]
        before = {str(p): core.digest(p) for p in protected if p.is_file()}
        args, model, opt, pipe, hidden = configure(run, config)
        native = GaussianModel(model.sh_degree, hidden)
        native.load_ply(str(snapshot / "point_cloud.ply"))
        native.load_model(str(snapshot))
        native._deformation.eval()
        baked = GaussianModel(model.sh_degree, hidden)
        timeline, _ = read_timeline(str(run / "dataset"))
        infos = readCamerasFromTransforms(str(run / "dataset"), "transforms_test.json",
                                         model.white_background, mapper=timeline)
        views = FourDGSdataset(infos, model, "blender")
        records = [r for r in config["dataset"]["records"] if r["split"] == "test"]
        if len(views) != len(records):
            raise ValueError("Validation camera count does not match saved records.")
        times = sorted(timeline)
        by_time = defaultdict(list)
        for index, record in enumerate(records):
            by_time[record["time"]].append(index)
        output.mkdir(parents=True)
        sequence = output / "ply"
        sequence.mkdir()
        preview = output / "previews"
        preview.mkdir()
        background = torch.tensor([1, 1, 1] if model.white_background else [0, 0, 0],
                                  dtype=torch.float32, device="cuda")
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
        small_font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 17)
        camera_ids = sorted({r["camera"] for r in records})
        writers = {c: imageio.get_writer(str(preview / f"{c}-comparison.mp4"),
                   fps=float(current["fps"]), codec="libx264", quality=8, macro_block_size=1)
                   for c in camera_ids}
        metrics, frames, samples = [], [], {}
        sample_indices = {0, len(times) // 2, len(times) - 1}
        first_xyz = previous_xyz = None
        motion = []
        started = time.perf_counter()
        try:
            for frame_index, source_time in enumerate(times):
                timestamp = timeline[source_time]
                t = torch.full((native.get_xyz.shape[0], 1), timestamp, device="cuda")
                xyz, scales, rotations, opacity, sh = native._deformation(
                    native.get_xyz, native._scaling, native._rotation, native._opacity,
                    native.get_features, t)
                if not all(torch.isfinite(x).all().item() for x in (xyz, scales, rotations, opacity, sh)):
                    raise ValueError(f"Non-finite Gaussian values at frame {frame_index}.")
                if not torch.isfinite(torch.exp(scales)).all() or (rotations.norm(dim=1) == 0).any():
                    raise ValueError(f"Invalid scale or rotation at frame {frame_index}.")
                # Standard Gaussian PLY stores log scales, opacity logits, and WXYZ quaternions.
                baked._xyz, baked._scaling, baked._rotation = xyz, scales, rotations
                baked._opacity = opacity
                baked._features_dc, baked._features_rest = sh[:, :1, :], sh[:, 1:, :]
                baked.active_sh_degree = native.active_sh_degree
                path = sequence / f"frame_{frame_index + 1:06d}.ply"
                baked.save_ply(str(path))
                # Reload the actual file, then use only the static rendering path.
                baked.load_ply(str(path))
                field_error = max(float((a - b).abs().max()) for a, b in (
                    (xyz, baked.get_xyz), (scales, baked._scaling), (rotations, baked._rotation),
                    (opacity, baked._opacity), (sh, baked.get_features)))
                if field_error > 1e-6:
                    raise ValueError("PLY round-trip changed Gaussian attributes.")
                if first_xyz is None:
                    first_xyz = xyz.clone()
                if previous_xyz is not None:
                    motion.append(float((xyz - previous_xyz).norm(dim=1).mean()))
                previous_xyz = xyz.clone()
                frames.append(dict(file=f"ply/{path.name}", time=source_time,
                                   model_time=timestamp, bytes=path.stat().st_size,
                                   sha256=core.digest(path), attribute_max_error=field_error))
                for index in by_time[source_time]:
                    record, cam = records[index], views[index]
                    direct = render(cam, native, pipe, background, stage="fine")["render"]
                    replay = render(cam, baked, pipe, background, stage="coarse")["render"]
                    max_error = float((direct - replay).abs().max())
                    if not torch.isfinite(replay).all() or max_error > 1e-5:
                        raise ValueError("Baked PLY rendering differs from the dynamic model.")
                    prediction = replay.clamp(0, 1)
                    target = cam.original_image.to("cuda")
                    mse = float(((prediction - target) ** 2).mean())
                    psnr = -10 * math.log10(max(mse, 1e-12))
                    score = float(ssim(prediction, target))
                    with Image.open(record["image"]) as source:
                        alpha = np.asarray(source.convert("RGBA"))[:, :, 3]
                        opaque_fraction = float(np.mean(alpha == 255))
                    metrics.append(dict(camera=record["camera"], frame=frame_index + 1,
                                        time=source_time, psnr_db=psnr, ssim=score,
                                        replay_max_error=max_error,
                                        source_opaque_fraction=opaque_fraction))
                    panels = []
                    for label, tensor in (("Maya reference", target), ("HUST dynamic", direct),
                                          ("Baked PLY playback", replay)):
                        rgb = (tensor.clamp(0, 1).permute(1, 2, 0).cpu().numpy() * 255).astype("uint8")
                        tile = Image.new("RGB", (480, 532), "#17212b")
                        tile.paste(Image.fromarray(rgb).resize((480, 480)), (0, 52))
                        ImageDraw.Draw(tile).text((12, 12), label, font=font, fill="white")
                        panels.append(tile)
                    row = Image.new("RGB", (1440, 560), "#17212b")
                    for col, tile in enumerate(panels):
                        row.paste(tile, (480 * col, 28))
                    ImageDraw.Draw(row).text((12, 4),
                        f"{record['camera']} | Frame {frame_index + 1:03d} | PSNR {psnr:.2f} dB | SSIM {score:.3f}",
                        font=small_font, fill="white")
                    writers[record["camera"]].append_data(np.asarray(row))
                    if frame_index in sample_indices:
                        row.save(preview / f"{record['camera']}-{frame_index + 1:03d}.png")
                        if record["camera"] == camera_ids[0]:
                            samples[frame_index] = row
                print(f"Verified frame {frame_index + 1}/{len(times)}", flush=True)
        finally:
            for writer in writers.values():
                writer.close()
        if {str(p): core.digest(p) for p in protected if p.is_file()} != before:
            raise RuntimeError("Training artifacts changed during this diagnostic.")
        summaries = {}
        for camera in camera_ids:
            rows = [r for r in metrics if r["camera"] == camera]
            summaries[camera] = dict(frames=len(rows),
                mean_psnr_db=float(np.mean([r["psnr_db"] for r in rows])),
                mean_ssim=float(np.mean([r["ssim"] for r in rows])))
        manifest = dict(format="Gaussian PLY sequence", status="complete", frame_count=len(frames),
            gaussian_count=int(native.get_xyz.shape[0]), sh_degree=native.active_sh_degree,
            fps=current["fps"], coordinate_system="Original normalized HUST world, Z up",
            normalization=current["normalization"],
            ue_coordinate_conversion_applied=False, frames=frames)
        core.write_json(output / "sequence.json", manifest)
        report = dict(status="passed", run=str(run), iteration=iteration,
            source_images_verified=current["all_images"], validation_views=len(metrics),
            cameras=summaries, gaussian_count=manifest["gaussian_count"],
            frames=len(frames), sequence_bytes=sum(f["bytes"] for f in frames),
            max_replay_error=max(r["replay_max_error"] for r in metrics),
            mean_ssim=float(np.mean([r["ssim"] for r in metrics])),
            mean_psnr_db=float(np.mean([r["psnr_db"] for r in metrics])),
            mean_source_opaque_fraction=float(np.mean([r["source_opaque_fraction"] for r in metrics])),
            mean_adjacent_displacement=float(np.mean(motion)),
            mean_first_to_last_displacement=float((previous_xyz - first_xyz).norm(dim=1).mean()),
            elapsed_seconds=time.perf_counter() - started,
            training_artifacts_unchanged=True, ue_playback_tested=False, vr_performance_tested=False,
            rows=metrics)
        core.write_json(output / "report.json", report)
        sheet = Image.new("RGB", (1440, 560 * len(samples)), "#17212b")
        for row_index, key in enumerate(sorted(samples)):
            sheet.paste(samples[key], (0, row_index * 560))
        sheet.save(output / "comparison.jpg", quality=92)
        rows = "\n".join(f"| {c} | {v['frames']} | {v['mean_psnr_db']:.2f} | {v['mean_ssim']:.4f} |"
                         for c, v in summaries.items())
        (output / "REPORT.md").write_text(
            f"# Gaussian sequence export test\n\nRun: `{run.name}`; fine iteration {iteration}.\n\n"
            f"Verified {current['all_images']} source PNGs against the saved capture identity.\n\n"
            f"Exported {len(frames)} PLY frames at {current['fps']} FPS, with {manifest['gaussian_count']:,} "
            f"Gaussians per frame and SH degree {native.active_sh_degree}. "
            f"Total size: {report['sequence_bytes'] / 1024**2:.2f} MiB.\n\n"
            "| Held-out camera | Frames | Mean PSNR (dB) | Mean SSIM |\n|---|---:|---:|---:|\n"
            + rows + "\n\n"
            f"Maximum pixel difference between native dynamic rendering and reloaded static PLY: "
            f"{report['max_replay_error']:.8g} (linear numeric range 0 to 1 before output encoding).\n\n"
            "Every exported frame was reloaded and rendered from both held-out cameras. "
            "Training configuration, checkpoint, status and final model files were unchanged.\n\n"
            "## Limits\n\n"
            "- This is a HUST rasterizer round-trip test, not an Unreal Engine or VR benchmark.\n"
            "- PLY files retain normalized training coordinates. A target importer must handle orientation, "
            "scale, quaternion conventions and spherical-harmonic directions consistently.\n"
            "- All trained content, including background and ground, is retained. No foreground extraction is performed.\n"
            "- Alpha compositing, relighting and runtime refraction in Unreal have not been validated.\n"
            "- Metrics average full 800 x 800 views and can be dominated by background pixels.\n\n"
            "See `comparison.jpg`, `previews/`, `sequence.json`, and `report.json`.\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
