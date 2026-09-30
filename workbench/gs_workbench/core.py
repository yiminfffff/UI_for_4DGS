"""Dataset validation, immutable run configuration, and environment discovery."""
import hashlib
import json
import math
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "HUST-Windows"
PYTHON = ROOT / ".envs/hust4dgs/python.exe"
RUNS = ROOT / "workbench-runs"
STATE = ROOT / ".cache/workbench"
PRESETS = {"Quick Preview": (300, 3000), "Quality": (3000, 20000), "Smoke Test": (20, 40)}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def validate_dataset(folder, stride=1, progress=None, cancelled=None):
    from PIL import Image
    folder = Path(folder).resolve()
    if stride < 1:
        raise ValueError("Temporal stride must be at least 1.")
    manifest_file = folder / "capture_manifest.json"
    manifest = read_json(manifest_file) if manifest_file.is_file() else None
    if manifest and manifest.get("status") != "complete":
        raise ValueError("This capture is incomplete. Finish the export in the capture plugin first.")
    source_plan = manifest["plan"] if manifest else {}
    if manifest and source_plan.get("fingerprint") != fingerprint({k: v for k, v in source_plan.items() if k != "fingerprint"}):
        raise ValueError("The capture plan has been modified or is invalid.")
    expected = {r["file_path"]: r for r in source_plan.get("records", [])}
    records, fovs, json_hashes = [], [], {}
    for split in ("train", "test"):
        path = folder / f"transforms_{split}.json"
        if not path.is_file():
            raise ValueError(f"Missing {path.name}. Select the dataset root, not its images folder.")
        data = read_json(path)
        json_hashes[split] = digest(path)
        fov = float(data["camera_angle_x"])
        if not math.isfinite(fov) or not 0.01 < fov < math.pi - 0.01:
            raise ValueError("Invalid camera field of view.")
        fovs.append(fov)
        if not data.get("frames"):
            raise ValueError(f"The {split} split is empty.")
        for entry in data["frames"]:
            relative = entry["file_path"].replace("\\", "/")
            if relative.lower().endswith(".png"):
                raise ValueError("Image paths must omit the .png extension for the HUST reader.")
            image = (folder / (relative + ".png")).resolve()
            if not image.is_relative_to(folder):
                raise ValueError("Dataset image paths must remain inside the selected folder.")
            t = float(entry["time"])
            matrix = entry["transform_matrix"]
            if (not math.isfinite(t) or not 0 <= t <= 1 or len(matrix) != 4
                    or any(len(row) != 4 for row in matrix)
                    or not all(math.isfinite(float(x)) for row in matrix for x in row)):
                raise ValueError(f"Invalid time or transform: {relative}")
            if any(abs(matrix[3][i] - (1 if i == 3 else 0)) > 1e-5 for i in range(4)):
                raise ValueError(f"Invalid homogeneous camera matrix: {relative}")
            determinant = sum(matrix[0][i] * (matrix[1][(i + 1) % 3] * matrix[2][(i + 2) % 3]
                              - matrix[1][(i + 2) % 3] * matrix[2][(i + 1) % 3]) for i in range(3))
            if abs(determinant - 1) > 1e-3:
                raise ValueError(f"Camera rotation is reflected or invalid: {relative}")
            for i in range(3):
                for j in range(3):
                    dot = sum(matrix[k][i] * matrix[k][j] for k in range(3))
                    if abs(dot - (1 if i == j else 0)) > 1e-3:
                        raise ValueError(f"Camera rotation contains scale or shear: {relative}")
            old = expected.get(relative)
            if manifest and (old is None or old["split"] != split or old["time"] != t
                             or old["transform_matrix"] != matrix):
                raise ValueError(f"Transform JSON does not match the capture manifest: {relative}")
            camera = old["camera"] if old else "View " + fingerprint(matrix)[:8]
            records.append(dict(file_path=relative, image=str(image), split=split, time=t,
                                transform_matrix=matrix, camera=camera,
                                maya_frame=old.get("maya_frame") if old else None))
            if old and "houdini_frame" in old:
                records[-1]["houdini_frame"] = old["houdini_frame"]
    if abs(fovs[0] - fovs[1]) > 1e-6:
        raise ValueError("Training and validation FOV must match.")
    if len({r["image"] for r in records}) != len(records):
        raise ValueError("Duplicate images or train/validation overlap detected.")
    if manifest and set(expected) != {r["file_path"] for r in records}:
        raise ValueError("The transform files do not include the full capture.")
    times = sorted({r["time"] for r in records})
    if len(times) < 2 or times[-1] <= 0:
        raise ValueError("Dynamic training needs at least two distinct times.")
    selected_times = set(times[::stride] + [times[-1]])
    selected = [r for r in records if r["time"] in selected_times]
    if not all(any(r["split"] == split for r in selected) for split in ("train", "test")):
        raise ValueError("Temporal sampling leaves an empty split. Use a smaller stride.")
    hashes = {}
    for index, record in enumerate(records):
        if cancelled and cancelled():
            raise InterruptedError("Validation cancelled.")
        path = Path(record["image"])
        if not path.is_file():
            raise ValueError(f"Missing image: {record['file_path']}.png")
        with Image.open(path) as image:
            if image.size != (800, 800) or image.format != "PNG":
                raise ValueError(f"Expected an 800 x 800 PNG: {path.name}")
            image.load()
        checksum = digest(path)
        if manifest and manifest.get("completed", {}).get(record["file_path"], {}).get("sha256") != checksum:
            raise ValueError(f"Image checksum does not match the capture export: {path.name}")
        hashes[record["file_path"]] = checksum
        if progress:
            progress(index + 1, len(records))
    identity = dict(transforms=json_hashes, images=hashes, stride=stride,
                    manifest=digest(manifest_file) if manifest else None)
    application = source_plan.get("application", "Maya")
    return dict(folder=str(folder), kind=f"{application} GS Capture" if manifest else "NeRF synthetic",
                fingerprint=fingerprint(identity), camera_angle_x=fovs[0], records=selected,
                all_images=len(records), selected_images=len(selected), times=len(selected_times),
                cameras=len({r["camera"] for r in selected}),
                train_images=sum(r["split"] == "train" for r in selected),
                test_images=sum(r["split"] == "test" for r in selected),
                fps=source_plan.get("source", {}).get("fps", 30),
                normalization=source_plan.get("normalization"),
                estimated_ram_gb=round(len(selected) * 800 * 800 * 3 * 4 * 2.5 / 1024**3 + 4, 1))


def validate_settings(settings):
    limits = {"coarse": (1, 10000), "fine": (1, 100000), "checkpoint_every": (1, 10000),
              "stride": (1, 1000), "sh_degree": (0, 3), "temporal_grid": (3, 300)}
    for name, (low, high) in limits.items():
        value = settings[name]
        if not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{name} must be an integer between {low} and {high}.")
    if settings["background"] not in ("white", "black"):
        raise ValueError("Unsupported background.")


def create_run(folder, dataset, settings):
    validate_settings(settings)
    folder = Path(folder).resolve()
    source = Path(dataset["folder"])
    if folder == source or source.is_relative_to(folder) or folder.is_relative_to(source):
        raise ValueError("Keep the training run and source dataset in separate folders.")
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("Run folder is not empty. Choose a new name, or open the existing run to resume.")
    if not (REPO / "train.py").is_file() or not PYTHON.is_file():
        raise ValueError("The local HUST training environment is missing.")
    folder.mkdir(parents=True, exist_ok=True)
    config = dict(version=1, dataset=dataset, settings=settings,
                  train_source_sha256=digest(REPO / "train.py"))
    config["fingerprint"] = fingerprint(config)
    write_json(folder / "run.json", config)
    prepared = folder / "dataset"
    for split in ("train", "test"):
        write_json(prepared / f"transforms_{split}.json", prepared_payload(dataset, split))
    manifest = source / "capture_manifest.json"
    if manifest.is_file():
        name = "houdini_capture_manifest.json" if dataset["kind"] == "Houdini GS Capture" else "maya_capture_manifest.json"
        write_json(folder / name, read_json(manifest))
    write_json(folder / "status.json", {"status": "ready", "message": "Ready to train"})
    return config


def prepared_payload(dataset, split):
    frames = [{"file_path": str(Path(r["image"]).with_suffix("")).replace("\\", "/"),
               "time": r["time"], "transform_matrix": r["transform_matrix"],
               "camera": r["camera"]} for r in dataset["records"] if r["split"] == split]
    return {"camera_angle_x": dataset["camera_angle_x"], "frames": frames}


def load_run(folder):
    config = read_json(Path(folder) / "run.json")
    if config.get("version") != 1 or config["fingerprint"] != fingerprint({k: v for k, v in config.items() if k != "fingerprint"}):
        raise ValueError("The run configuration is invalid or has been edited.")
    validate_settings(config["settings"])
    for split in ("train", "test"):
        if read_json(Path(folder) / "dataset" / f"transforms_{split}.json") != prepared_payload(config["dataset"], split):
            raise ValueError("Prepared dataset files changed. Restore them before resuming this run.")
    return config


def environment():
    env = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                 "QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
        env.pop(name, None)
    prefix = PYTHON.parent
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", CUDA_HOME=str(prefix / "Library"),
               CUDA_PATH=str(prefix / "Library"), TORCH_CUDA_ARCH_LIST="8.9", MAX_JOBS="4",
               MPLCONFIGDIR=str(ROOT / ".cache/matplotlib"), TORCH_HOME=str(ROOT / ".cache/torch"))
    env["PATH"] = os.pathsep.join(map(str, [prefix, prefix / "Scripts", prefix / "Library/bin"])) + os.pathsep + env.get("PATH", "")
    return env


def safe_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("Run names must use 1–64 letters, numbers, underscores, or hyphens.")
    return name
