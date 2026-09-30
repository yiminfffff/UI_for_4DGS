# 4DGS Workbench

A local Windows desktop app for **Maya/Houdini GS Capture → HUST 4DGaussians → image/video inspection**. The interface, messages, and source-code comments are in English. No browser, web server, or packaged executable is required.

## Start

Double-click **start-workbench.cmd** in the project root. The installed desktop environment is separate from the existing HUST/CUDA environment. Maya does not need to be running.

For a fresh checkout on this computer, run `setup-workbench.ps1` once. It installs the pinned desktop dependencies into `.envs/workbench`; it does not reinstall PyTorch or CUDA. The existing `.envs/hust4dgs` environment and `HUST-Windows` source tree are required for training.

## From Maya

The Houdini Solaris/Karma plugin in `houdini-gs-capture` exports the same dataset contract. Click **Open Training Workbench** after capture completion, or select its dataset folder here. It is identified as **Houdini GS Capture**; existing Maya datasets and runs remain compatible. See [Houdini capture setup](../houdini-gs-capture/README.md).

1. Export a complete dataset using GS Capture. A three-image preview is not a training dataset.
2. Click **Open Training Workbench** in the Maya panel. Restart Maya once if an older version of the panel is still loaded.
3. The workbench opens the export and validates its manifest, image checksums, camera transforms, and train/validation split.

If the workbench is already open, the capture is handed to the existing window. While a worker is busy, the request waits until that operation finishes. Only the most recent pending capture request is retained.

You can also use **Browse…** in the workbench and select the folder containing `capture_manifest.json` and both transform JSON files. **Use Sample** selects the installed bouncingballs dataset.

## Train

1. Select a dataset and click **Validate Dataset**. Inspect cameras and time samples in **Source Sequence**.
2. Choose a preset:

   | Preset | Coarse | Fine | Purpose |
   |---|---:|---:|---|
   | Smoke Test | 20 | 40 | Verify the pipeline, not image quality |
   | Quick Preview | 300 | 3,000 | Short visual experiment |
   | Quality | 3,000 | 20,000 | Longer training starting point; quality depends on the capture |

3. Set a new run name and output parent folder. Click **Start Training**.
4. Monitor the stage, iteration, loss, training-view PSNR, Gaussian count, and live **4DGS Preview**. Use **Show Log** for detailed events.

The run configuration is saved before training starts. **Resume Run** and **Export Video** always use that saved configuration; changing the top settings configures a new run. Existing run folders cannot be overwritten by Start Training.

### Settings

- **Temporal stride:** use every Nth sampled time, retaining the last time. This reduces the number of loaded training images without modifying the source export. Validation still checks the complete source dataset.
- **Temporal grid:** temporal representation resolution, not the number of input frames. Minimum 3, because HUST's temporal smoothness regularizer uses a second difference.
- **Checkpoint every:** save the model and optimizer at this interval, at stage completion, and when Stop & Save is requested.
- **SH degree:** view-dependent appearance complexity, from 0 to 3.
- **Background:** white or black for compositing the exported straight-alpha PNGs. This is baked into training; it does not create an independently compositable transparent asset.
- **Animate opacity:** optional time-dependent opacity deformation. Experimental for fluids/fractures; evaluate the result on your material and animation.

V1 uses 800×800 images, batch size 1, HUST's D-NeRF-style deformation settings, and the first CUDA GPU. The estimated RAM figure is a planning estimate, not a guaranteed peak. The worker checks available system RAM before loading the dataset. Large captures may need a larger temporal stride or shorter segments.

## Stop, resume, and reopen

- **Stop & Save** requests a stop at the next completed training iteration. During initial data loading, stopping may take longer. A saved checkpoint includes model weights, optimizer state, deformation accumulation, RNG state, stage, and iteration.
- **Resume Run** continues the saved coarse or fine stage. A fine checkpoint skips the coarse stage. Camera sampling is rebuilt, so resumed runs are not promised to be bit-identical to uninterrupted runs.
- If a run stopped before its first checkpoint, **Start Saved Run** restarts that saved configuration from the beginning.
- **Force Stop** terminates immediately after an explicit confirmation. Work after the last checkpoint is lost; checkpoint replacement is atomic.
- Closing the window during training requests Stop & Save and waits for the worker to return. It does not leave training silently running in the background.
- **Open Run…** loads a folder containing `run.json`. V1 opens runs created by this workbench; it does not import arbitrary pretrained PLY files or old command-line experiment folders.

Do not edit `run.json` or prepared transform files. Source images remain in place and are rechecked before training, resuming, or rendering. Moving or changing those images requires a new run or restoring the original paths/content.

## Render and inspect

Click **Export Video** to select the render path and playback FPS. The left preview continues to show the source sequence; the right preview is the interactive model.

- **First validation camera:** render all selected times for the first held-out camera. Each output has a matching source/reference image. The reported PSNR is the mean for this camera, not the entire validation set. On a generic synthetic dataset with a different pose per image, the first validation camera may have only one frame.
- **Orbit (160 frames):** render HUST's standard orbit and time path. Orbit images do not have matching ground-truth views. This path is most useful for captures normalized by the Maya plugin.
- **FPS:** playback frame rate for the exported MP4. It controls playback duration and does not change the training timeline.
- Use the frame slider or **Play** for an in-app image-sequence preview. **Open Video** opens the MP4 in the system video player.

Rendering streams images to PNG and MP4 rather than retaining the entire output sequence on the GPU. A stopped render leaves its partial output folder; only completed renders replace the workbench's latest-render entry.

## Files

```text
workbench-runs/my-run/
  run.json                  Saved source identity and training configuration
  status.json               Last recorded training state
  latest.pt                 Resumable model + optimizer checkpoint
  checkpoint.json           Checkpoint stage and iteration
  maya_capture_manifest.json
  dataset/                  Selected transform records; images stay at source
  model/point_cloud/        HUST Gaussian and deformation snapshots
  preview.png               Most recent training preview
  live-camera.json          Transient interactive camera request during training
  renders/                  Rendered PNG sequences, MP4 files, and reports
  latest_render.json
  worker.log
```

Gaussian PLY alone is not the complete dynamic model. Keep the deformation files and saved configuration with it. The workbench's **Add to Unreal...** action evaluates the dynamic model and creates a separate baked animation asset.

### Diagnostic PLY sequence export

`test_export_sequence.py --run <completed-run> --output <new-folder>` is a separate diagnostic,
run with the existing HUST environment. It checks the source capture, bakes each selected
time into a standard Gaussian PLY, reloads each file, and compares static PLY rendering
with the dynamic model from every held-out view. It writes a sequence manifest,
PSNR/SSIM measurements, comparison images, and videos. It preserves the trained model.

This diagnostic retains HUST coordinates and all trained content, including background.
It does not add an export button to the desktop app, perform foreground extraction, or
certify UE/VR rendering. Playback timing currently assumes consecutive source frames;
use a capture with frame step 1 and temporal stride 1 for these diagnostic videos.

## Interactive result viewer and Unreal import

The permanent **4DGS Preview** opens automatically when loading a saved run. **Alt + left drag** orbits, **Alt + middle drag** pans, **Alt + right drag** dollies; the wheel zooms and **F** resets the view. **Match Source Camera** uses the exact selected source-camera transform. Navigating manually turns matching off; selecting another source camera then leaves the free view unchanged until matching is enabled again. Both previews share animation time. Use **Play**, the time slider, resolution and snapshot selectors to inspect saved fine-stage snapshots, or coarse snapshots when no fine snapshot exists.

During training, preview starts after the point cloud is initialized, before the first optimization iteration. It renders the current in-memory model inside the training process through both coarse and fine stages, without loading a second model. Requests are coalesced between iterations; refresh frequency adapts to rendering cost. Preview therefore adds some training overhead and is not a guaranteed display FPS. When idle, a separate resident local process renders saved snapshots. Offline video rendering and UE export temporarily release this viewer's GPU memory and reopen it afterward.

**Add to Unreal...** bakes the selected snapshot, installs the project-owned GS4D plugin, and imports a new animation asset into a closed UE 5.8 project. See `../unreal/README.md` for playback and limitations. This is separate from the older diagnostic PLY exporter described above.

The desktop live preview shows the actual model after the completed iteration, including opacity resets. A temporary reset notice explains the possible pale appearance while opacity recovers. Sampled training/test validation in `validation.jsonl` and legacy headless preview images retain their pre-reset evaluation timing. Saved checkpoints represent the actual state after the iteration. These display/logging changes do not change training parameters or repair an existing model.

## Environment and plugin maintenance

**Check GPU** queries the NVIDIA GPU and driver independently of the training environment. **Training Environment** checks the pinned HUST source, deformation model, PyTorch/CUDA dependencies and an actual CUDA rasterization. It offers extension repair for the existing environment and **Setup Instructions** for a fresh installation. Driver and compiler prerequisites remain guided steps; see [Environment setup](ENVIRONMENT-SETUP.md).

**UE Plugin** selects a project, checks the engine build and project-owned GS4D installation, and offers **Install / Update** before any training run exists. Installation uses the desktop environment and does not require CUDA or a trained model. Close Unreal Editor before installing. Modified plugin files are protected. **Add to Unreal...** remains the separate model-baking and asset-import action.

## Implementation and validation

The app uses PySide6. Training and rendering run under the existing HUST Python environment through QProcess. A guarded in-memory adapter adds safe-stop, checkpoint, progress, and finite-loss checks to the pinned HUST training loop; it does not edit upstream files. Checkpoints load with `weights_only=True`.

See `VALIDATION.md` for the tests performed on this computer. Smoke-test renders demonstrate connectivity and model loading, not production fluid/fracture quality or VR performance.

Technical references: [Qt QProcess](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html), [pinned PySide6 Essentials](https://pypi.org/project/PySide6-Essentials/6.8.3/), and the local HUST source in `HUST-Windows`.
