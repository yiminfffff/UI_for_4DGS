"""Arnold interactive Render Sequence backend, one camera/frame per transaction."""
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import maya.cmds as cmds
import maya.mel as mel

from . import dataset


def ensure_arnold():
    if not cmds.pluginInfo("mtoa", query=True, loaded=True):
        cmds.loadPlugin("mtoa")
    import mtoa.core
    mtoa.core.createOptions()


def set_value(attr, value):
    if isinstance(value, str) or (value is None and cmds.getAttr(attr, type=True) == "string"):
        cmds.setAttr(attr, value or "", type="string")
    else:
        cmds.setAttr(attr, value)


@contextmanager
def temporary_settings(values):
    """Rollback even when applying the overrides fails halfway through."""
    saved = []
    current = cmds.currentTime(query=True)
    modified = cmds.file(query=True, modified=True)
    try:
        for attr, value in values.items():
            if not cmds.objExists(attr):
                raise RuntimeError("This Arnold version is missing a required setting: " + attr)
            saved.append((attr, cmds.getAttr(attr)))
            set_value(attr, value)
        yield
    finally:
        errors = []
        for attr, value in reversed(saved):
            try:
                set_value(attr, value)
            except Exception as exc:
                errors.append(f"{attr}: {exc}")
        cmds.currentTime(current, edit=True)
        if not errors:
            cmds.file(modified=modified)
        else:
            raise RuntimeError("Some render settings could not be restored. Check the log: " + "; ".join(errors))


def render_one(session, record, allow_batch_test=False):
    if cmds.about(batch=True) and not allow_batch_test:
        raise RuntimeError("Open the panel in the Maya GUI to render. This tool uses interactive Render Sequence.")
    ensure_arnold()
    camera = next(c for c in session.plan["cameras"] if c["id"] == record["camera"])
    work_root = session.root / ".work"
    work_root.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="frame_", dir=str(work_root)))
    frame = record["maya_frame"]
    settings = session.plan["settings"]
    overrides = {
        "defaultRenderGlobals.currentRenderer": "arnold",
        "defaultRenderGlobals.imageFilePrefix": (work / "capture").as_posix(),
        "defaultRenderGlobals.animation": True,
        "defaultRenderGlobals.startFrame": frame,
        "defaultRenderGlobals.endFrame": frame,
        "defaultRenderGlobals.byFrameStep": 1,
        "defaultRenderGlobals.extensionPadding": 4,
        "defaultRenderGlobals.putFrameBeforeExt": True,
        "defaultRenderGlobals.outFormatControl": 0,
        "defaultRenderGlobals.periodInExt": 1,
        "defaultRenderGlobals.useFrameExt": False,
        "defaultRenderGlobals.useRenderRegion": False,
        "defaultResolution.width": dataset.SIZE,
        "defaultResolution.height": dataset.SIZE,
        "defaultResolution.pixelAspect": 1.0,
        "defaultResolution.deviceAspectRatio": 1.0,
        "defaultArnoldDriver.aiTranslator": "png",
        "defaultArnoldDriver.prefix": "",
        "defaultArnoldDriver.pngFormat": 0,
        "defaultArnoldDriver.pngUnpremultAlpha": True,
        "defaultArnoldDriver.pngSkipAlpha": False,
        "defaultArnoldDriver.colorManagement": 1,
        "defaultArnoldDriver.outputMode": 2,
        "defaultArnoldRenderOptions.motion_blur_enable": False,
        "defaultArnoldRenderOptions.aovMode": 0,
        "defaultArnoldRenderOptions.AASamples": settings["aa_samples"],
        "defaultArnoldRenderOptions.renderDevice": settings["device"],
    }
    option = "OverrideFileOutputDirectory"
    old_output = cmds.optionVar(query=option) if cmds.optionVar(exists=option) else None
    try:
        with temporary_settings(overrides):
            cmds.optionVar(stringValue=(option, work.as_posix()))
            cmds.currentTime(frame, edit=True)
            if not cmds.about(batch=True):
                mel.eval("showRenderView();")
            # Exactly the synchronous backend used by mtoa.cmds.arnoldRender.arnoldSequenceRender.
            # Do not use arnoldRenderView: its deferred IPR path is not a completion signal.
            cmds.arnoldRender(seq="", w=dataset.SIZE, h=dataset.SIZE,
                             cam=camera["shape"], srv="")
            images = list(work.rglob("*.png"))
            if len(images) != 1:
                raise RuntimeError(f"Expected one Arnold output image; found {len(images)}. Temporary folder: {work}")
            session.commit(record, images[0])
    finally:
        if old_output is None:
            cmds.optionVar(remove=option)
        else:
            cmds.optionVar(stringValue=(option, old_output))
        # tempfile generated this exact child; never remove a user-selected directory.
        if work.parent.resolve() == work_root.resolve() and work.name.startswith("frame_"):
            shutil.rmtree(work, ignore_errors=True)
