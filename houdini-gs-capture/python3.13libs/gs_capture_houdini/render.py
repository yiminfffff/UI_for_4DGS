"""Karma rendering and explicit scene-linear to straight-alpha PNG conversion."""
from pathlib import Path

import hou
import numpy as np
import OpenImageIO as oiio

from . import dataset, scene


def convert_image(source, destination, plan):
    image = oiio.ImageBuf(str(source))
    if not image.read():
        raise RuntimeError("Could not decode the Karma image: " + image.geterror())
    spec = image.spec()
    if (spec.width, spec.height) != (dataset.SIZE, dataset.SIZE):
        raise RuntimeError("Karma output must be exactly 800 x 800 pixels.")
    names = list(spec.channelnames)
    if not all(name in names for name in ("R", "G", "B", "A")):
        raise RuntimeError("Karma output must contain R, G, B, and A channels.")
    pixels = np.asarray(image.get_pixels(oiio.FLOAT))[:, :, [names.index(n) for n in ("R", "G", "B", "A")]].copy()
    if not np.isfinite(pixels).all():
        raise RuntimeError("Karma produced non-finite pixels. Check the source materials and volumes.")
    # EXR beauty is associated. Divide before the nonlinear display transform.
    alpha = np.clip(pixels[:, :, 3:4], 0, 1)
    pixels[:, :, :3] = np.divide(pixels[:, :, :3], alpha,
                                out=np.zeros_like(pixels[:, :, :3]), where=alpha > 1e-8)
    pixels[:, :, 3:4] = alpha
    straight = oiio.ImageBuf(oiio.ImageSpec(dataset.SIZE, dataset.SIZE, 4, oiio.FLOAT))
    straight.set_pixels(oiio.ROI.All, pixels)
    source_info = plan["source"]
    display = oiio.ImageBufAlgo.ociodisplay(straight, source_info["color_display"],
        source_info["color_view"], fromspace=source_info["scene_linear"], unpremult=False,
        colorconfig=source_info["ocio_config"])
    if display.has_error:
        raise RuntimeError("Color conversion failed: " + display.geterror())
    display.specmod().attribute("oiio:UnassociatedAlpha", 1)
    display.set_write_format(oiio.UINT8)
    if not display.write(str(destination)):
        raise RuntimeError("Could not write the PNG image: " + display.geterror())


class KarmaRenderer:
    def __init__(self, plan):
        self.plan = plan
        self.nodes = []
        try:
            rig = hou.node(plan["source"]["rig_lop"])
            settings = rig.parent().createNode("karmarendersettings", "gs_capture_render_settings")
            self.nodes.append(settings)
            settings.setInput(0, rig)
            settings.parm("res_mode").set("manual")
            settings.parm("res_mode").pressButton()
            values = dict(resolutionx=dataset.SIZE, resolutiony=dataset.SIZE,
                          engine=plan["settings"]["engine"],
                          pathtracedsamples=plan["settings"]["samples"],
                          enablemblur=1, mblur=0, enabledof=0)
            for name, value in values.items():
                scene.set_parm(settings, name, value)
            rop = rig.parent().createNode("usdrender_rop", "gs_capture_render")
            self.nodes.append(rop)
            rop.setInput(0, settings)
            scene.set_parm(rop, "loppath", settings.path())
            scene.set_parm(rop, "rendersettings", settings.parm("primpath").evalAsString())
            self.settings, self.rop = settings, rop
        except Exception:
            self.close()
            raise

    def render(self, record, folder):
        folder = Path(folder)
        exr, png = folder / "beauty.exr", folder / "beauty.png"
        for path in (exr, png):
            if path.exists():
                path.unlink()
        hou.setFrame(record["houdini_frame"])
        scene.set_parm(self.settings, "camera", f"{scene.CAMERA_ROOT}/{record['camera']}")
        scene.set_parm(self.settings, "picture", str(exr))
        scene.set_parm(self.rop, "outputimage", str(exr))
        self.rop.render(frame_range=(record["houdini_frame"], record["houdini_frame"]), verbose=True)
        if not exr.is_file():
            raise RuntimeError("Karma did not write an image. Check the render log and Houdini license.")
        convert_image(exr, png, self.plan)
        return png

    def close(self):
        for node in reversed(self.nodes):
            node.destroy()
        self.nodes.clear()
