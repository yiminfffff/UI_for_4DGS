"""Solaris bounds, editable fixed cameras, and capture validation."""
from contextlib import contextmanager
import math
from pathlib import Path

import hou
from pxr import Gf, Sdf, Usd, UsdGeom

from . import dataset

RIG_NAME = "GS_Capture"
CAMERA_ROOT = "/GSCapture"
TAG = "gs_capture_version"


@contextmanager
def preserve_frame():
    frame = hou.frame()
    try:
        yield
    finally:
        hou.setFrame(frame)


def source_node(path):
    node = hou.node(path)
    if not isinstance(node, hou.LopNode):
        raise ValueError("Choose a Solaris LOP node containing the geometry, materials, and lights.")
    ancestor = node
    while ancestor:
        if ancestor.userData(TAG):
            raise ValueError("Choose the source node before GS_Capture, not a node inside the capture rig.")
        ancestor = ancestor.parent()
    return node


def selected_source():
    nodes = [n for n in hou.selectedNodes() if isinstance(n, hou.LopNode) and not n.userData(TAG)]
    if len(nodes) != 1:
        raise ValueError("Select one source LOP node in Solaris first.")
    return nodes[0].path()


def selected_prims():
    for pane in hou.ui.paneTabs():
        if isinstance(pane, hou.SceneViewer):
            paths = pane.currentSceneGraphSelection()
            if paths:
                return list(paths)
    raise ValueError("Select the effect primitives in the Solaris Scene Graph Tree first, or enter their USD paths.")


def target_paths(text):
    paths = list(dict.fromkeys(text.replace(",", " ").split()))
    if not paths:
        raise ValueError("Enter one or more USD framing primitive paths.")
    for value in paths:
        path = Sdf.Path(value)
        if not path.IsAbsolutePath() or not path.IsPrimPath() or value.startswith(CAMERA_ROOT):
            raise ValueError("Use explicit absolute geometry paths, such as /World/Effect. Wildcards are not supported.")
    return paths


def get_stage(node):
    stage = node.stage()
    errors = node.errors()
    if not stage or errors:
        raise ValueError("The source LOP could not cook: " + "; ".join(errors))
    return stage


def bounds_at(stage, targets, frame):
    cache = UsdGeom.BBoxCache(Usd.TimeCode(frame), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
                             useExtentsHint=False, ignoreVisibility=False)
    total = Gf.Range3d()
    for path in targets:
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.IsActive():
            raise ValueError(f"Framing primitive is missing or inactive at frame {frame}: {path}")
        box = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        if not box.IsEmpty():
            total.UnionWith(box)
    return total


def scan_bounds(node, targets, frames, progress=None):
    total = Gf.Range3d()
    with preserve_frame():
        for index, frame in enumerate(frames):
            hou.setFrame(frame)
            stage = get_stage(node)
            box = bounds_at(stage, targets, frame)
            if not box.IsEmpty():
                total.UnionWith(box)
            if progress and not progress(index + 1, len(frames)):
                raise RuntimeError("Bounds scan cancelled.")
    if total.IsEmpty():
        raise ValueError("The selected primitives have no visible render bounds in the sampled range.")
    bounds = list(total.GetMin()) + list(total.GetMax())
    if not all(math.isfinite(v) for v in bounds):
        raise ValueError("The scene contains invalid or infinite bounds.")
    dataset.normalization(bounds)
    return bounds


def get_rig(node):
    rig = node.parent().node(RIG_NAME)
    if not rig or not rig.userData(TAG) or rig.input(0) != node:
        raise ValueError("Create the camera rig for this source LOP first.")
    return rig


def set_parm(node, name, value):
    parm = node.parm(name)
    if parm is None:
        raise RuntimeError(f"Houdini is missing the required parameter {node.path()}/{name}.")
    parm.deleteAllKeyframes()
    parm.set(value)


def create_rig(node, bounds, focal=35.0, margin=1.15, elevations=(10.0, 45.0)):
    if node.parent().node(RIG_NAME):
        raise ValueError("GS_Capture already exists. Adjust its cameras, or delete that rig before rebuilding.")
    source = get_stage(node)
    if source.GetPrimAtPath(CAMERA_ROOT):
        raise ValueError("The source stage already contains /GSCapture. Rename that prim before creating the rig.")
    up = str(UsdGeom.GetStageUpAxis(source)).lower()
    center, _ = dataset.normalization(bounds)
    radius = math.sqrt(sum(((bounds[i + 3] - bounds[i]) / 2) ** 2 for i in range(3)))
    distance = radius / math.sin(math.atan(36 / (2 * focal))) * margin
    rig = None
    with hou.undos.group("Create 4DGS Cameras"):
        try:
            rig = node.parent().createNode("subnet", RIG_NAME)
            rig.setInput(0, node)
            rig.setUserData(TAG, dataset.VERSION)
            previous = rig.indirectInputs()[0]
            for index in range(16):
                ring, local = divmod(index, 8)
                angle = math.radians(local * 45 + ring * 22.5)
                elevation = math.radians(elevations[ring])
                offset = [distance * math.cos(elevation) * math.cos(angle),
                          distance * math.sin(elevation), distance * math.cos(elevation) * math.sin(angle)]
                if up == "z":
                    offset = [offset[0], -offset[2], offset[1]]
                position = Gf.Vec3d(*(center[i] + offset[i] for i in range(3)))
                backward = (position - Gf.Vec3d(*center)).GetNormalized()
                vertical = Gf.Vec3d(0, 1, 0) if up == "y" else Gf.Vec3d(0, 0, 1)
                right = Gf.Cross(vertical, backward).GetNormalized()
                camera_up = Gf.Cross(backward, right).GetNormalized()
                matrix = list(right) + [0] + list(camera_up) + [0] + list(backward) + [0] + list(position) + [1]
                camera = rig.createNode("camera", f"CAM{index + 1:03d}")
                camera.setInput(0, previous)
                parms = dict(primpath=f"{CAMERA_ROOT}/{camera.name()}", focalLength=focal,
                             horizontalAperture=36, aspectratiox=1, aspectratioy=1,
                             fStop=0, projection="perspective",
                             clippingRange1=max(1e-8, (distance - radius) * 0.01),
                             clippingRange2=(distance + radius) * 4,
                             xn__shutteropen_0ta=0, xn__shutterclose_nva=0)
                for key, value in parms.items():
                    set_parm(camera, key, value)
                camera.parmTuple("t").set(list(position))
                camera.parmTuple("r").set(hou.Matrix4(matrix).extractRotates())
                previous = camera
            output = rig.node("output0")
            output.setInput(0, previous)
            output.setDisplayFlag(True)
            rig.layoutChildren()
            rig.moveToGoodPosition()
            rig.setDisplayFlag(True)
        except Exception:
            if rig is not None:
                rig.destroy()
            raise
    return rig


def camera_info(stage, camera_id, frame):
    path = f"{CAMERA_ROOT}/{camera_id}"
    camera = UsdGeom.Camera(stage.GetPrimAtPath(path))
    if not camera:
        raise ValueError(f"The rig is missing {path}.")
    time = Usd.TimeCode(frame)
    focal = float(camera.GetFocalLengthAttr().Get(time))
    horizontal = float(camera.GetHorizontalApertureAttr().Get(time))
    vertical = float(camera.GetVerticalApertureAttr().Get(time))
    if (camera.GetProjectionAttr().Get(time) != UsdGeom.Tokens.perspective or focal <= 0
            or horizontal <= 0 or abs(horizontal - vertical) > 1e-5):
        raise ValueError(f"{camera_id}: use a square perspective camera with positive focal length.")
    for attr, label in ((camera.GetHorizontalApertureOffsetAttr(), "horizontal aperture offset"),
                        (camera.GetVerticalApertureOffsetAttr(), "vertical aperture offset"),
                        (camera.GetFStopAttr(), "depth of field"), (camera.GetExposureAttr(), "exposure")):
        if abs(float(attr.Get(time) or 0)) > 1e-7:
            raise ValueError(f"{camera_id}: disable {label}.")
    prim = camera.GetPrim()
    for name in ("karma:camera:use_lensshader", "karma:camera:lensshader", "karma:camera:materialbinding"):
        value = prim.GetAttribute(name).Get(time)
        if value:
            raise ValueError(f"{camera_id}: custom camera lens shaders are not supported.")
    matrix = camera.ComputeLocalToWorldTransform(time)
    axes = [Gf.Vec3d(*list(matrix[i])[:3]) for i in range(3)]
    if (any(abs(a.GetLength() - 1) > 1e-5 for a in axes)
            or any(abs(Gf.Dot(axes[i], axes[j])) > 1e-5 for i, j in ((0, 1), (0, 2), (1, 2)))
            or Gf.Dot(Gf.Cross(axes[0], axes[1]), axes[2]) < 0.99999):
        raise ValueError(f"{camera_id}: reset camera scale, reflection, and shear.")
    fov = 2 * math.atan(horizontal / (2 * focal))
    return dict(id=camera_id, prim_path=path, world_matrix=[v for row in matrix for v in row],
                camera_angle_x=fov, intrinsics=dict(fx=dataset.SIZE / (2 * math.tan(fov / 2)),
                fy=dataset.SIZE / (2 * math.tan(fov / 2)), cx=400, cy=400))


def color_config():
    import PyOpenColorIO as ocio
    path = hou.getenv("OCIO")
    if not path or not Path(path).is_file():
        raise ValueError("This version requires a file-based OCIO configuration in Houdini's OCIO environment.")
    return path, ocio.Config.CreateFromFile(path)


def collect_plan(settings, source_path, targets, progress=None, require_saved=True):
    scene_file = Path(hou.hipFile.path())
    if not scene_file.is_file() or (require_saved and hou.hipFile.hasUnsavedChanges()):
        raise ValueError("Save the Houdini scene, including the camera rig, before validation or rendering.")
    node = source_node(source_path)
    rig = get_rig(node)
    frames = dataset.frames_for(settings["start"], settings["end"], settings["step"])
    ocio_path, ocio = color_config()
    if settings["display"] not in list(ocio.getDisplays()) or settings["view"] not in list(ocio.getViews(settings["display"])):
        raise ValueError("The selected color display/view is unavailable in the current OCIO configuration.")
    reference, up, units = None, None, None
    with preserve_frame():
        for index, frame in enumerate(frames):
            hou.setFrame(frame)
            stage = get_stage(rig)
            current_up = str(UsdGeom.GetStageUpAxis(stage)).lower()
            current_units = UsdGeom.GetStageMetersPerUnit(stage)
            current = [camera_info(stage, f"CAM{i:03d}", frame) for i in range(1, 17)]
            if reference is None:
                reference, up, units = current, current_up, current_units
            elif (up != current_up or units != current_units or any(abs(a - b) > 1e-5
                    for old, new in zip(reference, current)
                    for a, b in zip(old["world_matrix"] + [old["camera_angle_x"]],
                                    new["world_matrix"] + [new["camera_angle_x"]]))):
                raise ValueError(f"A camera, stage up axis, or scene scale changes at frame {frame}. Fixed cameras are required.")
            if progress and not progress(index + 1, len(frames) * 2):
                raise RuntimeError("Validation cancelled.")
    bounds = scan_bounds(node, targets, frames,
                         (lambda i, n: progress(n + i, n * 2)) if progress else None)
    source = dict(application="Houdini", scene=str(scene_file), scene_sha256=dataset.digest_file(scene_file),
                  houdini=hou.applicationVersionString(), source_lop=node.path(), rig_lop=rig.path(),
                  targets=targets, fps=hou.fps(), up_axis=up, meters_per_unit=units,
                  take=hou.takes.currentTake().name(), ocio_config=ocio_path,
                  ocio_sha256=dataset.digest_file(ocio_path), color_display=settings["display"],
                  color_view=settings["view"], scene_linear=ocio.getRoleColorSpace("scene_linear"),
                  visibility="All render-visible source stage content; framing targets do not isolate geometry.")
    return dataset.build_plan(settings, reference, bounds, source)
