# Validation record

Validated on 2026-09-17 on the current Windows machine:

- NVIDIA RTX 4090 Laptop GPU, 16 GB VRAM
- HUST Python 3.10, PyTorch 2.7.1+cu128, CUDA 12.8
- Desktop Python 3.10, PySide6 Essentials 6.8.3, Pillow 11.3.0
- Maya GS Capture 0.1.0 / Maya 2027 export contract

## Passed

1. **Real GPU and extension check.** Imported both installed CUDA extensions and executed the GPU nearest-neighbor operation.
2. **Real training pause/resume.** Trained the installed bouncingballs sample with temporal stride 5; paused coarse training at iteration 11; resumed into fine training; paused fine training at iteration 11; resumed to fine iteration 40. The fine resume skipped the coarse stage. This was a short integration test, not a converged model.
3. **Model reload and video rendering.** Loaded the saved fine-stage model and rendered all 160 orbit frames, PNGs, and an MP4.
4. **Actual desktop subprocess workflow.** Used the app's QProcess and event handling to check the GPU, validate a Maya-plugin test export with 16 cameras / 28 training images / 4 validation images / 2 time samples, run 5 coarse + 10 fine iterations, and render the first held-out camera at both times. Both output images had matching source references. This fixture contains generated structural-test images, not the user's fluid/fracture simulation.
5. **Dataset and run guards.** Rejected incomplete captures, modified image contents, mismatched camera transforms, overwriting an existing run, edited prepared transform files, and temporal grids below 3. Confirmed separation of the 14 training and 2 validation cameras.
6. **UI inspection.** Built and inspected the English desktop at 1280×920. Corrected missing fonts in the offscreen screenshot environment, made training controls remain visible while scrolling settings, and checked English source strings/comments.
7. **Maya handoff checks.** Verified the plugin's desktop executable, dataset arguments, and cleaned Python/Qt environment using a mocked launch. Verified that the desktop queues a capture request while busy and validates the received 16-camera export once idle. The handoff check does not open an extra visible desktop window.

The workbench installs its desktop dependencies separately and does not edit the HUST source. The Maya plugin was extended with an Open Training Workbench handoff. Maya-specific Python/Qt environment variables are removed from the launched desktop process.

## September 19 interactive viewer and export checks

The resident HUST viewer loaded the user's final 26,877-point model and rendered different poses and times at 512 pixels. Warm request times were approximately 11–12 ms in this test (including image conversion and JPEG encoding; not end-to-end display FPS). The actual PySide widget passed orbit and playback interaction tests, with an English UI screenshot under `test-results/live-viewer`.

The existing four dataset contract tests and real CUDA pause/resume/160-frame render integration test passed again. A separate short training run with deliberately frequent resets verified that previews precede resets in both stages and that validation records are saved (`reset-timing.json`). The user's production training files were not retrained.

The `.gs4d` export was decoded and rendered through CUDA at frames 0, 28 and 56. Mean absolute byte differences from the live neural renderer were below 0.00002, with maximum difference 1, confirming coordinate/covariance/SH/opacity preservation at sampled times (`ue-roundtrip.json`). This is an export fidelity test, not a claim of identical rendering in UE.

The actual workbench **Add to Unreal...** action completed baking, plugin installation and UE asset import in 49.75 seconds on this machine, creating a 57-frame, 26,877-point asset (`ue-workflow.json`). The exporter preserved the selected production snapshot.

The self-authored runtime/editor plugin compiled with UE 5.8.2. The asset factory created the playback actor from the imported asset, and real D3D12 screenshots captured normalized times 0, 0.5 and 1. Editor playback advanced automatically. The test map uses neutral exposure and tone mapping; images preserve the reconstruction defects seen in HUST. Reports and images are in `../unreal/test-results/`. This does not validate headset stereo or a VR performance budget.

## September 30 layout, live preview and maintenance checks

- Inspected the English desktop with horizontal top settings and equal source/model previews at 1280 and 1500 pixels wide. The header eyebrow and flat result-view selector were removed.
- A real short CUDA training run produced interactive frames at coarse iteration 0 and fine iteration 0, updated through optimization, and accepted changed camera requests without a second viewer process (`test-results/live-training.json`). Preview refresh adapts to rendering cost; these tests do not establish a fixed display rate.
- The actual viewer widget verified exact source-camera matching, automatic matching disablement during navigation, preservation of the free view after source-camera changes, and playback (`test-results/live-viewer/ui.json`).
- Independent GPU detection and the training-environment dialog passed. Backend validation constructed the deformation network and rendered a finite, nonempty CUDA image (`test-results/environment-dialog.json`).
- The actual plugin dialog installed GS4D into an isolated project without a trained run, changed its status from Missing to Ready, and protected deliberately modified source files (`test-results/maintenance.json`).
- The four dataset contract tests, desktop workflow with a Maya capture fixture, and real coarse/fine pause/resume plus 160-frame video integration passed again. The user's production model was not retrained.
- A saved coarse iteration 11 snapshot loaded and rendered successfully with the coarse-stage renderer (`test-results/coarse-viewer.json`).

## Limits

These tests do not establish production fluid/fracture reconstruction quality, final convergence, or VR performance. Resume restores model/optimizer/RNG state but does not promise identical sampling order to an uninterrupted run. Force termination, machine shutdown during a checkpoint write, long multi-thousand-frame captures, and every third-party scene/cache combination have not been exhaustively simulated.

## Reproduce

From the project root:

```powershell
.\.envs\workbench\Scripts\python.exe workbench\tests\test_contracts.py
.\.envs\workbench\Scripts\python.exe workbench\tests\integration.py
.\.envs\workbench\Scripts\python.exe workbench\tests\desktop_workflow.py
.\.envs\workbench\Scripts\python.exe workbench\tests\ui_smoke.py
```

The Maya contract and desktop tests use the fixture produced by `maya-gs-capture/tests/maya_integration.py`. Test outputs and structured reports are under `workbench/test-results/`; they are separate from normal training runs.
