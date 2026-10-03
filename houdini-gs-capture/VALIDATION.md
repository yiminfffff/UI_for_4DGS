# Validation — Houdini 22.0.368

Tested locally on Windows on 2026-09-17 with Houdini 22.0.368 / Python 3.13. Tests use an animated USD sphere and dome light, isolated test preferences, and a saved non-commercial fixture. No user production HIP was edited.

| Check | Result |
| --- | --- |
| Animation bounds and 16 editable Camera LOPs | Passed |
| Karma CPU, 16 cameras x 2 frames | 32 RGBA PNGs, 800 x 800 |
| Karma XPU preview | 3 RGBA PNGs, 800 x 800 |
| Native Houdini UI and shelf installer | Passed; English labels and screenshot inspected |
| Read playback range | Passed: 1 to 2, 32 images |
| UI background worker and responsive event loop | Passed |
| Stop after current image, then resume | Stopped after 2 preview images; reused them and rendered the remaining image |
| Complete dataset from UI | Passed: 32 images |
| Camera projection vs. USD world-to-camera | Matched within 1e-7 for all cameras |
| Camera forward direction vs. framing center | Matched within 1e-6 |
| Animated camera rejection | Passed |
| Very small effect and camera clipping planes | Passed at radius 0.0001 |
| Premultiplied EXR to straight-alpha display PNG | Matched the OCIO CPU reference within 1.5/255 |
| Damaged PNG and modified configuration rejection | Passed |
| Full worker resume with matching images | All 32 skipped in command-line resume |
| Preview excluded from training | Passed |
| Source HIP content after rendering | SHA-256 unchanged |
| Workbench dataset validation | 28 training + 4 validation images, 16 cameras, 2 times |
| Native HUST readCamerasFromTransforms | 28 training + 4 validation, tensors [3, 800, 800], times 0 and 1 |
| Existing workbench contract regression suite | 4 tests passed |
| Existing completed Maya training run | Still loads as Maya GS Capture |

The fixture was rendered with Apprentice. Its watermark is visible and preserved. Four samples kept tests short, so images are intentionally noisy. XPU validation covers this small fixture, not production fluid materials or GPU memory limits. No new training run or UE playback test was performed for this plugin task.

Artifacts under `test-results/` include `fixture.hipnc`, `capture/`, `preview/`, `xpu-preview/`, `ui-preview.png`, `ui-result.json`, `ui-workflow-result.json`, and `ui-workflow.log`. Test outputs are excluded from version control.

The initial UI harness called `hou.exit()` from a Qt timer, causing a Houdini shutdown crash after the success report was written. The harness now uses native `quit`; the final UI smoke test exited without the shutdown error. This test-only shutdown code is not part of the plugin.

Final numerical/integrity suite: **7 tests passed**. Final workbench validation also passed on the UI-rendered images. Run these checks as the same Windows user that rendered the files; Python's temporary directories use private permissions, so a separate sandbox account cannot necessarily decode another account's rendered output.

## Reproduce

Run from this plugin folder. Use a fresh test-results directory for a new fixture: a changed saved HIP intentionally invalidates existing dataset fingerprints.

```powershell
& 'C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe' tests/integration.py
& 'C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe' python3.13libs/gs_capture_houdini/worker.py --job test-results/preview-job.json
& 'C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe' python3.13libs/gs_capture_houdini/worker.py --job test-results/full-job.json
& 'C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe' tests/verify.py
& 'C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe' tests/xpu_preview.py
```

GUI tests use a separate `HOUDINI_USER_PREF_DIR` containing the required `__HVER__` token and Houdini's `waitforui` startup option. They load only their own fixture and quit the test instance when finished.
