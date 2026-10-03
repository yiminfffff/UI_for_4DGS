"""Camera math shared by the interactive viewer and its tests (Z-up, OpenGL)."""
import math


def orbit_pose(target, yaw, pitch, distance):
    cp, sp, cy, sy = math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
    back = [cp * cy, cp * sy, sp]
    right = [-sy, cy, 0]
    up = [-sp * cy, -sp * sy, cp]
    return [[right[i], up[i], back[i], target[i] + distance * back[i]] for i in range(3)] + [[0, 0, 0, 1]]


def duration(config):
    records = config["dataset"]["records"]
    frames = [r.get("houdini_frame", r.get("maya_frame")) for r in records]
    frames = [f for f in frames if f is not None]
    fps = float(config["dataset"].get("fps", 24))
    return max(1 / fps, (max(frames) - min(frames)) / fps if frames else
               (len({r["time"] for r in records}) - 1) / fps)


def snapshots(run, stage="fine"):
    pattern = "coarse_iteration_*" if stage == "coarse" else "iteration_*"
    return sorted(int(p.name.split("_")[-1]) for p in (run / "model/point_cloud").glob(pattern)
                  if p.name.split("_")[-1].isdigit() and (p / "deformation.pth").is_file()
                  and (p / "point_cloud.ply").is_file())
