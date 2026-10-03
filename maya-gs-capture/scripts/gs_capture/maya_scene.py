"""Scene analysis and fixed-camera rig. All Maya calls run on the main thread."""
import math
from contextlib import contextmanager
from pathlib import Path

import maya.cmds as cmds
import maya.api.OpenMaya as om

from . import dataset

RIG = "GS_CameraRig"
TAG = "gsCaptureVersion"


@contextmanager
def preserve_time():
    time = cmds.currentTime(query=True)
    try:
        yield
    finally:
        cmds.currentTime(time, edit=True)


def selected_targets():
    targets = cmds.ls(selection=True, long=True, objectsOnly=True) or []
    targets = [x for x in targets if cmds.nodeType(x) == "transform"
               and x != "|" + RIG and not x.startswith("|" + RIG + "|")]
    if not targets:
        raise ValueError("Select the effect objects or a group in Maya first.")
    return list(dict.fromkeys(targets))


def scan_bounds(targets, frames, progress=None):
    bounds = [float("inf")] * 3 + [-float("inf")] * 3
    if any(not cmds.objExists(x) for x in targets):
        raise ValueError("Selected effect objects have been renamed or deleted. Select them again.")
    with preserve_time():
        for index, frame in enumerate(frames):
            cmds.currentTime(frame, edit=True)
            box = cmds.exactWorldBoundingBox(targets, ignoreInvisible=True)
            if not all(math.isfinite(x) for x in box):
                raise ValueError(f"Invalid bounding box at frame {frame}.")
            for axis in range(3):
                bounds[axis] = min(bounds[axis], box[axis])
                bounds[axis + 3] = max(bounds[axis + 3], box[axis + 3])
            if progress and not progress(index + 1, len(frames)):
                raise RuntimeError("Bounds scan cancelled.")
    dataset.normalization(bounds)
    return bounds


def cameras():
    if not cmds.objExists(RIG + "." + TAG):
        raise ValueError("Create the GS camera rig first.")
    result = cmds.listRelatives(RIG, allDescendents=True, fullPath=True, type="camera") or []
    result = sorted(result, key=lambda x: cmds.getAttr(x + ".gsCameraId")
                    if cmds.objExists(x + ".gsCameraId") else "")
    if len(result) != 16 or any(not cmds.objExists(x + ".gsCameraId") for x in result):
        raise ValueError("The GS rig must contain all 16 capture cameras.")
    return result


def create_rig(bounds, focal=35.0, distance_multiplier=1.15, elevations=(10.0, 45.0)):
    if cmds.objExists(RIG):
        raise ValueError("GS_CameraRig already exists. Adjust it manually, or delete the old rig in Maya before rebuilding.")
    center, _ = dataset.normalization(bounds)
    sphere = math.sqrt(sum(((bounds[i + 3] - bounds[i]) / 2) ** 2 for i in range(3)))
    fov = 2 * math.atan(36.0 / (2 * focal))
    distance = sphere / math.sin(fov / 2) * distance_multiplier
    up = cmds.upAxis(query=True, axis=True)
    selection = cmds.ls(selection=True, long=True) or []
    cmds.undoInfo(openChunk=True, chunkName="Create GS Capture Rig")
    created = None
    try:
        created = cmds.group(empty=True, name=RIG)
        cmds.addAttr(created, longName=TAG, dataType="string")
        cmds.setAttr(created + "." + TAG, dataset.VERSION, type="string")
        for index in range(16):
            ring, local = divmod(index, 8)
            angle = math.radians(local * 45 + ring * 22.5)
            elevation = math.radians(elevations[ring])
            offset = [distance * math.cos(elevation) * math.cos(angle),
                      distance * math.sin(elevation),
                      distance * math.cos(elevation) * math.sin(angle)]
            if up == "z":
                offset = [offset[0], -offset[2], offset[1]]
            position = om.MVector(*(center[i] + offset[i] for i in range(3)))
            backward = (position - om.MVector(*center)).normal()
            vertical = om.MVector(0, 1, 0) if up == "y" else om.MVector(0, 0, 1)
            right = (vertical ^ backward).normal()
            camera_up = (backward ^ right).normal()
            transform, shape = cmds.camera(name=f"CAM{index + 1:03d}")
            transform = cmds.parent(transform, created)[0]
            shape = cmds.listRelatives(transform, shapes=True, fullPath=True)[0]
            matrix = list(right) + [0] + list(camera_up) + [0] + list(backward) + [0] + list(position) + [1]
            cmds.xform(transform, worldSpace=True, matrix=matrix)
            values = {"focalLength": focal, "horizontalFilmAperture": 36 / 25.4,
                      "verticalFilmAperture": 36 / 25.4, "filmFit": 1,
                      "nearClipPlane": max(distance * 0.0001, 0.001),
                      "farClipPlane": max(distance * 10, 1000), "renderable": False,
                      "displayResolution": True}
            for attr, value in values.items():
                cmds.setAttr(shape + "." + attr, value)
            cmds.addAttr(shape, longName="gsCameraId", dataType="string")
            cmds.setAttr(shape + ".gsCameraId", f"CAM{index + 1:03d}", type="string", lock=True)
    except Exception:
        if created and cmds.objExists(created):
            cmds.delete(created)
        raise
    finally:
        cmds.select(selection, replace=True) if selection else cmds.select(clear=True)
        cmds.undoInfo(closeChunk=True)
    return cameras()


def camera_info(shape):
    sel = om.MSelectionList()
    sel.add(shape)
    fn = om.MFnCamera(sel.getDagPath(0))
    if fn.isOrtho():
        raise ValueError("V1 supports perspective cameras only.")
    # Reject unsupported optical effects explicitly rather than silently exporting bad poses.
    defaults = {"horizontalFilmOffset": 0, "verticalFilmOffset": 0, "filmFitOffset": 0,
                "lensSqueezeRatio": 1, "cameraScale": 1, "preScale": 1, "postScale": 1,
                "filmTranslateH": 0, "filmTranslateV": 0, "filmRollValue": 0,
                "panZoomEnabled": 0, "depthOfField": 0, "shakeEnabled": 0,
                "aiEnableDOF": 0}
    for attr, default in defaults.items():
        if cmds.objExists(shape + "." + attr) and abs(cmds.getAttr(shape + "." + attr) - default) > 1e-7:
            raise ValueError(f"{shape}: disable or reset {attr}.")
    if (cmds.objExists(shape + ".ai_translator")
            and cmds.getAttr(shape + ".ai_translator") not in ("", "persp_camera")):
        raise ValueError("V1 supports the standard Arnold perspective lens only.")
    left, right, bottom, top = fn.getRenderingFrustum(1.0)
    near = fn.nearClippingPlane
    if abs(left + right) > 1e-6 or abs(bottom + top) > 1e-6 or abs((right-left)-(top-bottom)) > 1e-6:
        raise ValueError("The effective camera frustum must be centered and square.")
    fov = 2 * math.atan((right - left) / (2 * near))
    world = list(sel.getDagPath(0).inclusiveMatrix())
    axes = [om.MVector(*world[i:i + 3]) for i in (0, 4, 8)]
    if (any(abs(a.length() - 1) > 1e-6 for a in axes)
            or any(abs(axes[i] * axes[j]) > 1e-6 for i, j in ((0, 1), (0, 2), (1, 2)))
            or (axes[0] ^ axes[1]) * axes[2] < 0.99999):
        raise ValueError("The camera or its parent has scale, reflection, or shear. Reset these before positioning the camera.")
    return {"id": cmds.getAttr(shape + ".gsCameraId"), "shape": shape,
            "world_matrix": world, "camera_angle_x": fov,
            "focal_length_mm": fn.focalLength,
            "intrinsics": {"fx": dataset.SIZE / (2 * math.tan(fov / 2)),
                           "fy": dataset.SIZE / (2 * math.tan(fov / 2)),
                           "cx": dataset.SIZE / 2, "cy": dataset.SIZE / 2}}


def collect_plan(settings, targets, progress=None):
    scene = cmds.file(query=True, sceneName=True)
    if not scene or not Path(scene).is_file() or cmds.file(query=True, modified=True):
        raise ValueError("Save the Maya scene, including the camera rig and current settings, before validation or rendering.")
    if cmds.editRenderLayerGlobals(query=True, currentRenderLayer=True) != "defaultRenderLayer":
        raise ValueError("V1 requires the master render layer. Switch to it before capture.")
    for attr in ("preMel", "postMel", "preRenderLayerMel", "postRenderLayerMel", "preRenderMel", "postRenderMel"):
        if cmds.getAttr("defaultRenderGlobals." + attr):
            raise ValueError("V1 does not support custom render callbacks. Remove this callback in your capture scene: " + attr)
    frames = dataset.frames_for(settings["start"], settings["end"], settings["step"])
    shapes = cameras()
    reference = None
    with preserve_time():
        for index, frame in enumerate(frames):
            cmds.currentTime(frame)
            current = [camera_info(s) for s in shapes]
            if reference is None:
                reference = current
            elif any(abs(a - b) > 1e-6
                     for old, new in zip(reference, current)
                     for a, b in zip(old["world_matrix"] + [old["camera_angle_x"]],
                                     new["world_matrix"] + [new["camera_angle_x"]])):
                raise ValueError(f"A camera moves or changes FOV at frame {frame}. V1 requires fixed cameras.")
            if progress and not progress(index + 1, len(frames) * 2):
                raise RuntimeError("Validation cancelled.")
    bounds = scan_bounds(targets, frames,
                         (lambda i, n: progress(n + i, 2 * n)) if progress else None)
    source = {"scene": scene, "scene_sha256": dataset.digest_file(scene),
              "targets": targets, "fps": om.MTime(1, om.MTime.uiUnit()).asUnits(om.MTime.kSeconds) ** -1,
              "linear_unit": cmds.currentUnit(query=True, linear=True),
              "up_axis": cmds.upAxis(query=True, axis=True), "maya": cmds.about(version=True),
              "mtoa": cmds.pluginInfo("mtoa", query=True, version=True),
              "visibility": "All render-visible objects in the master layer; targets only define bounds.",
              "color_view": cmds.colorManagementPrefs(query=True, viewTransformName=True),
              "color_display": cmds.colorManagementPrefs(query=True, displayName=True)}
    return dataset.build_plan(settings, reference, bounds, source)
