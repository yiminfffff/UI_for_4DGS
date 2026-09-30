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
