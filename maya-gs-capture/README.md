# Render for 4DGS - Maya 2027 / Arnold

A fixed-camera animated capture panel using Maya 2027 and its bundled Arnold. UI, messages and source comments are English. No additional Python packages, web service or training environment are required.

## Install

1. Keep this folder beside `workbench` in the extracted repository.
2. Open Maya 2027 and drag `install.py` from File Explorer into the viewport.
3. The panel opens and adds the **GSCapture** shelf. Use its **GS** button to reopen it.

Moving the source folder requires running the installer again. The installer does not replace Maya libraries or edit Maya.env. Alternatively, in Maya's Python Script Editor:

```python
import sys
sys.path.insert(0, r"C:\4DGS\maya-gs-capture\scripts")
import gs_capture
gs_capture.show()
```

Replace the path with your extraction folder. Remove the GSCapture shelf to uninstall its entry point.

## Capture

1. Cache the simulation for every sampled frame. Set materials, lights and consistent color settings.
2. Select effect objects/groups and click **Use Selection**. Targets define framing; all render-visible objects on the master layer still render.
3. In **Frame and Timeline**, set start/end/step or click **Use Current Timeline**. Confirm caching. At least two time samples are required.
4. Click **Scan Animation Bounds and Create 16 Cameras**. The fixed rig uses two rings of eight, staggered by 22.5 degrees; elevations initially 10 and 45 degrees.
5. Adjust camera transforms manually if needed, keeping cameras fixed and without scale animation. An existing rig is not silently overwritten.
6. Save the scene, choose output/device/AA and click **Validate**, then **Preview 3 Images**. Test GPU compatibility with the scene before a full GPU capture.
7. Click **Render** for the full dataset. Stop waits for the current image; rendering again with identical inputs resumes missing/damaged images.
8. After completion, **Open Training Workbench** hands the dataset to the adjacent desktop application. Its environment must already be set up.

Do not edit the scene while capturing. To resume, keep external caches, textures and lights unchanged; choose a new export folder after changing dependencies.

## Output contract

```text
MyEffect/
  capture_manifest.json
  transforms_train.json
  transforms_test.json
  images/CAM001/CAM001_SEQ0001.png
  images/CAM001/CAM001_SEQ0002.png
  ...
  images/CAM016/...
```

Images are 800 x 800, 8-bit RGBA PNG with straight alpha and the current Maya View Transform baked into color. Motion blur is disabled. SEQ0001 is the first sampled time, not the original scene frame. The manifest retains frame/time/FPS mapping and original transforms. The default holdouts are CAM004 and CAM012; the remaining fourteen cameras train the model.

Camera metadata uses exact horizontal FOV, OpenGL camera-to-world transforms, normalized time and centered/scaled Z-up coordinates. Source scene geometry/cameras are not scaled. No COLMAP step is required. Dataset JSON is published only after full image validation.

Animated cameras, arbitrary resolution, farm distribution and physical material reconstruction are outside this version. Fluid/refraction/fracture quality needs scene-specific testing. See [VALIDATION.md](VALIDATION.md) for local tests; no test renders or user scenes are bundled.
