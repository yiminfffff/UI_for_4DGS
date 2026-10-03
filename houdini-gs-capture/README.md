# Render for 4DGS — Houdini

A local Solaris / Karma capture panel for **Houdini 22.0.368 on Windows**, with an English UI, messages, and source comments. It exports the HUST-compatible dataset consumed by the training workbench next to this plugin.

## Install and open

Keep this folder next to `workbench`. In Houdini, open **Windows > Python Shell** and run:

```python
import runpy
runpy.run_path(r"C:\4DGS\houdini-gs-capture\install.py", run_name="__main__")
```

The installer opens the panel, adds the **4DGS** shelf, and registers this folder in the current Houdini user's `packages/gs_capture_houdini.json`. It does not change `houdini.env` or the Houdini installation. If you move this folder, run the installer again. After restarting Houdini, enable the **4DGS** shelf from the shelf menu if it is not visible.

You can also reopen the panel from the Python Shell after installation:

```python
import gs_capture_houdini
gs_capture_houdini.show()
```

No pip packages are required. Python 3.13, Qt, USD, NumPy, OpenImageIO, and OpenColorIO come from Houdini.

## Capture workflow

1. Cache the simulation for the whole capture range. Bring the effect into Solaris and finish the materials and lights. Save external caches to disk.
2. Select the final **source LOP**, then click **Use Selection** beside **Source LOP**. Choose the node before the capture rig; its output must include all geometry, materials, and lighting needed by Karma.
3. Enter the effect's USD paths under **Framing Primitives**, for example `/World/Effect`, or select those primitives in Solaris and click their **Use Selection** button. Separate multiple paths with commas or spaces. Wildcards are not supported.
4. Set the start, end, and step, or click **Use Current Timeline** to read the playback range. Check **Simulation is cached for every sampled frame**.
5. Click **Scan and Create 16 Cameras**. The plugin scans every sampled frame and creates a `GS_Capture` subnet beside the source, with 16 editable Camera LOPs. Two staggered rings of eight initially use elevations of 10 and 45 degrees. Camera names are `CAM001` through `CAM016`.
6. Adjust cameras if needed, then **save the HIP file**. Keep all cameras fixed across the capture range, with a shared field of view and square filmback. Click **Validate Scene**.
7. Choose an empty dataset folder, renderer, samples, and color display/view. Use **Render 3 Previews** to check lighting, framing, materials, and transparency. Previews go to a separate sibling folder ending in `_preview`.
8. Click **Render**. **Stop After Current Image** waits for the current image, then stops. Click **Render** again with the same scene and settings to resume.
9. After completion, click **Open Training Workbench**. The workbench recognizes the dataset as **Houdini GS Capture**.

The render worker loads the saved HIP in a separate `hython` process. The panel remains responsive. Scene changes after launching a capture are not included in that capture. The worker never saves over the source HIP.

## Scene and render behavior

**Framing Primitives define framing and normalization only.** All render-visible content in the source LOP is included. Remove unwanted ground planes, sky geometry, and props upstream if they should not become part of the trained result. Lights remain part of the scene.

Use disk caches and file-backed assets. Session-only Python variables, unsaved edits, interactive selections, or viewer-only visibility overrides are not a reproducible source for the background worker. USD primitives need valid render bounds; missing/inactive targets or empty bounds stop validation.

The worker creates its own Karma Render Settings LOP:

- CPU or XPU, with configurable path-traced samples.
- 800 x 800, square perspective cameras, no depth of field or motion blur.
- EXR beauty converted to 8-bit **straight-alpha RGBA PNG**.
- Explicit OCIO display/view conversion from the configuration's `scene_linear` role. The default is **sRGB - Display / ACES 1.0 - SDR Video** when available. This panel setting does not automatically follow a Solaris viewer override.

Existing custom Render Settings options such as extra AOVs, denoisers, ray limits, or light-path expressions are not copied. Materials and lights come from the source stage. Check previews, especially for volumes and refractive effects; CPU and XPU can differ in material support and appearance.

## Dataset and resume

```text
capture/
  capture_manifest.json
  transforms_train.json
  transforms_test.json
  images/
    CAM001/
      CAM001_SEQ0001.png
      CAM001_SEQ0002.png
    ...
    CAM016/
      ...
```

Sequence numbers are consecutive sampled images, starting at 1. For example, frames 1001, 1003, 1005 export as SEQ0001, SEQ0002, SEQ0003. The manifest records original `houdini_frame`, seconds, FPS, camera intrinsics/transforms, bounds, normalization, source HIP hash, OCIO hash, and settings.

The default holdouts are **CAM004 and CAM012**: 14 training cameras and two validation cameras at every sampled time. Time is normalized to 0–1. World positions are centered and uniformly normalized; Y-up USD scenes are rotated to Z-up. OpenGL camera axes remain +X right, +Y up, -Z forward.

Transforms files are published only after all images pass decoding and checksum verification. Preview folders are not training datasets. Damaged or missing images are rendered again. Folders belonging to another scene/configuration are rejected, and concurrent jobs cannot write to the same output.

To resume, keep the saved HIP, settings, and external assets unchanged. External asset contents are not recursively hashed: **change Asset Revision and choose a new output folder whenever caches, textures, lights, or other external dependencies change**. The source HIP and OCIO files themselves are hashed.

## License and limits

The local test renderer used **Apprentice**, whose images contain a Houdini watermark. The plugin preserves it. These test images validate the pipeline; they are not clean training material. Use an appropriately licensed Houdini/Karma environment for clean production captures. A `.hipnc` scene remains non-commercial; installing another license does not automatically convert it.

CPU full capture, XPU previews, native UI, stop/resume, PNG alpha, camera projection, workbench validation, and HUST loading were exercised locally. See [VALIDATION.md](VALIDATION.md). Production fluid and fracture caches still need their own preview/capture test.

This version targets Windows/Houdini 22.0/Python 3.13. Linux installation, farm submission, animated cameras, arbitrary resolution, and OBJ/Mantra rendering are not included.

## Remove

Close the panel and remove only `gs_capture_houdini.json` from your Houdini user `packages` directory, then restart Houdini. Remove the **4DGS** shelf from the shelf menu if desired. HIP scenes and exported datasets remain on disk.

## References

- [SideFX: Houdini packages](https://www.sidefx.com/docs/houdini/ref/plugins.html)
- [SideFX: command-line startup and waitforui](https://www.sidefx.com/docs/houdini/ref/commandline.html)
- [SideFX: shelf API](https://www.sidefx.com/docs/houdini/hom/hou/shelves.html)
