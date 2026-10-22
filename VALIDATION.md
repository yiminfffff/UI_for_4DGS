# Source release validation

The installed tools were exercised on the original Windows development machine. The publication bundle was assembled on 2026-09-30. A complete fresh-machine install from this archive has not yet been performed.

- Maya 2027 / Arnold capture: projection, animation bounds, time mapping, image export, resume checks and desktop handoff.
- Houdini 22.0.368 / Solaris-Karma: CPU capture, XPU previews, fixed cameras, PNG conversion/alpha, stop/resume, dataset checks and HUST loading.
- Workbench: dataset contract tests, actual CUDA coarse/fine pause/resume, model reload, 160-frame orbit video and a Maya capture desktop workflow.
- Live viewer: initialized point-cloud preview, coarse/fine updates in the training process, exact source-camera matching, free navigation, playback and coarse snapshot reload.
- Maintenance: real backend render check and independent installation into a test Unreal project; modified plugin source was protected.
- Startup: inaccessible and malformed recent-run entries no longer abort window creation; the actual desktop window opened after the fix.
- Unreal: source compiled with UE 5.8.2; baked animation imported and editor playback observed. Headset/VR performance is unverified.

Some included integration scripts require locally created DCC fixtures, the optional upstream sample or an existing saved run. They are not a self-contained CI suite. The small startup test can run after desktop setup:

```powershell
.envs/workbench/Scripts/python.exe workbench/tests/test_startup.py
```

Local reports, screenshots, datasets, scene files and trained models are excluded from publication. Detailed historical component validation documents describe original-machine results, not a guarantee for another system.

## GPU playback update — 22 October 2026

- The current plugin source compiled against UE 5.8.2 (build 56702186), including its global compute shader, then ran in the Blast and trench standalone scenes.
- Whole-scene playback measured 475.99 FPS in Blast over 12 seconds, and 115.26 FPS during one uninterrupted 1.501-second Q explosion in the trench. Hardware, complete frame-time results, sampling method and limitations are in [unreal/PERFORMANCE.md](unreal/PERFORMANCE.md).
- All 8,133 Gaussians and the 21.59 MiB original export were retained. Stable-ID interpolation removed the old eight-updates-per-second sample hold without changing the file format.
- At a fixed camera and baked sample with interpolation disabled, the GPU versus old CPU screenshot foreground had PSNR 57.53 dB, mean absolute error 0.115/255, maximum difference 2/255 and the same thresholded image bounds. This supports that tested view/state, not universal pixel identity or visibility guarantees.
- Trench validation passed colliding spawn, movement, jump, mouse input, Q restart, synchronized lights and final hidden/lights-off state. A clean playback covered all 12 source indices, 159 requested animation times and 147 within-sample interpolation-alpha changes. Those continuity values are requested states shared with the render selection logic, not GPU image readback.
- The first-shot screenshots can synchronously stall the game, so the uninterrupted third playback supplies the trench normal-playback timing. The result is a short original-machine check, not a sustained gameplay average, fresh-machine installation, Shipping or VR benchmark.

No scene assets, rendered screenshots, user-local paths, datasets, trained models or generated engine binaries are included in this source update. Existing historical validation sections above describe the earlier tools and remain for context.
