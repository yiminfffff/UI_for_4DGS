"""HUST-compatible dataset contract and resumable output bookkeeping."""
import hashlib
import json
import math
from pathlib import Path

VERSION = "0.1.0"
SIZE = 800


def frames_for(start, end, step):
    if step < 1 or end <= start:
        raise ValueError("End frame must be greater than start frame; step must be at least 1.")
    frames = list(range(int(start), int(end) + 1, int(step)))
    if len(frames) < 2:
        raise ValueError("HUST dynamic training requires at least two distinct time samples.")
    return frames


def digest_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    tmp.replace(path)


def normalization(bounds):
    center = [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)]
    extent = max(bounds[i + 3] - bounds[i] for i in range(3))
    if not math.isfinite(extent) or extent < 1e-7:
        raise ValueError("Capture bounds are empty or too small. Select the effect geometry.")
    # Longest half-extent becomes 0.9, leaving room inside HUST's default bounds.
    return center, 1.8 / extent


def export_pose(world_matrix, center, scale, up_axis="y"):
    """USD row-vector world matrix -> OpenGL column-vector c2w, Z-up world.

    Camera axes stay +X right, +Y up, -Z forward. Only WORLD axes are rotated.
    Scale only the translation, never the orthonormal camera basis.
    """
    m = [[float(world_matrix[col * 4 + row]) for col in range(4)] for row in range(4)]
    for i in range(3):
        m[i][3] = (m[i][3] - center[i]) * scale
    if up_axis == "y":
        m = [m[0], [-x for x in m[2]], m[1], m[3]]
    return m


def build_plan(settings, cameras, bounds, source):
    times = frames_for(settings["start"], settings["end"], settings["step"])
    center, scale = normalization(bounds)
    holdout = set(settings["test_cameras"])
    ids = {c["id"] for c in cameras}
    if not holdout or not holdout < ids:
        raise ValueError("Validation cameras must exist, with at least one camera left for training.")
    fov = cameras[0]["camera_angle_x"]
    if any(abs(c["camera_angle_x"] - fov) > 1e-6 for c in cameras):
        raise ValueError("All cameras must share the same field of view. This HUST reader accepts one global FOV.")
    records = []
    for index, frame in enumerate(times, 1):
        for cam in cameras:
            name = f"{cam['id']}_SEQ{index:04d}"
            records.append({
                "camera": cam["id"], "houdini_frame": frame, "sequence": index,
                "time": (frame - times[0]) / (times[-1] - times[0]),
                "seconds": (frame - times[0]) / source["fps"],
                "file_path": f"images/{cam['id']}/{name}",
                "split": "test" if cam["id"] in holdout else "train",
                "transform_matrix": export_pose(cam["world_matrix"], center, scale,
                                                source["up_axis"]),
            })
    contract = dict(version=VERSION, application="Houdini", settings=settings, source=source, cameras=cameras,
                    bounds=bounds, normalization=dict(center=center, scale=scale,
                    exported_world_up="z", camera_convention="OpenGL: +X right, +Y up, -Z forward"),
                    camera_angle_x=fov, width=SIZE, height=SIZE, records=records)
    return {**contract, "fingerprint": fingerprint(contract)}


def image_valid(path, size=SIZE):
    # Decode the entire image rather than trusting a filename or PNG header.
    import OpenImageIO as oiio
    image = oiio.ImageBuf(str(path))
    if not image.read():
        image.geterror()
        return False
    spec = image.spec()
    return spec.width == size and spec.height == size and spec.nchannels == 4


class OutputSession:
    """Only images recorded after successful rendering can be resumed."""
    def __init__(self, root, plan, preview=False):
        self.root = Path(root).resolve()
        self.plan = plan
        self.preview = preview
        self.manifest_path = self.root / "capture_manifest.json"
        self.state = {"plan": plan, "status": "pending", "completed": {}, "errors": []}
        if self.manifest_path.exists():
            old = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if old["plan"]["fingerprint"] != plan["fingerprint"]:
                raise ValueError("This folder belongs to a different scene or configuration. Choose a new output folder.")
            self.state = old
        elif self.root.exists() and any(self.root.iterdir()):
            raise ValueError("The output folder is not empty and has no matching capture manifest. Choose an empty folder.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.state["status"] = "rendering_preview" if preview else "rendering"
        # Never leave training entry points pointing at an incomplete/repaired dataset.
        for name in ("transforms_train.json", "transforms_test.json"):
            path = self.root / name
            if path.exists():
                path.unlink()
        self.flush()

    def path(self, record):
        return self.root / (record["file_path"] + ".png")

    def done(self, record):
        path = self.path(record)
        previous = self.state["completed"].get(record["file_path"])
        return (bool(previous) and path.is_file() and image_valid(path)
                and digest_file(path) == previous["sha256"])

    def commit(self, record, temporary_image):
        if not image_valid(temporary_image):
            raise RuntimeError("Karma did not produce a complete 800 x 800 RGBA PNG. This image will not be marked complete.")
        final = self.path(record)
        final.parent.mkdir(parents=True, exist_ok=True)
        Path(temporary_image).replace(final)
        self.state["completed"][record["file_path"]] = {"sha256": digest_file(final)}
        self.flush()

    def finish(self):
        records = self.plan["records"]
        if not all(self.done(record) for record in records):
            raise RuntimeError("Images are missing or damaged. The training dataset cannot be published yet.")
        if not self.preview:
            for split in ("train", "test"):
                data = {"camera_angle_x": self.plan["camera_angle_x"], "w": SIZE, "h": SIZE,
                        "frames": [{key: r[key] for key in
                                    ("file_path", "time", "transform_matrix")}
                                   for r in records if r["split"] == split]}
                write_json(self.root / f"transforms_{split}.json", data)
        self.state["status"] = "preview_complete" if self.preview else "complete"
        self.flush()

    def stop(self, error=None):
        self.state["status"] = "failed" if error else "cancelled"
        if error:
            self.state["errors"].append(str(error))
        self.flush()

    def flush(self):
        write_json(self.manifest_path, self.state)
