# GS4D local Unreal player

This project-owned plugin imports HUST animation baked by the workbench. It does not require a third-party Gaussian player. This publication contains plugin source only. Build the editor binaries with your exact UE 5.8 installation before using workbench installation/import.

## Workbench workflow

The workbench header's **UE Plugin** button checks and installs the project plugin independently of training or asset export. Select a `.uproject` and the matching UE engine, close Unreal Editor, then use **Install / Update** when available. This operation needs neither CUDA nor a trained run. Modified installed source files are protected; incompatible engine binaries require rebuilding. **Add to Unreal...** below performs the separate animation bake and asset import.

1. Close Unreal Editor and open a saved workbench training run.
2. Click **Add to Unreal...**, select a `.uproject`, the engine folder, and a fine-stage snapshot.
3. Click **Export and Add Asset**. The workbench bakes source time samples, installs `Plugins/GS4D`, enables the import dependencies, and creates a new folder under `/Game/GS4D`.
4. Open the project and drag its **Sequence** asset into a level. Enable **Preview In Editor** on the Gaussian component for editor animation. Play in Editor plays automatically. Use **Normalized Time**, **Play**, **Pause**, **Loop**, and **Playback Rate** to control it.

The original project descriptor is backed up as `.uproject.before-gs4d`. Existing asset folders are never replaced. Modified plugin files are protected by an installation manifest. Imports use an unattended Unreal process; stop requests during import wait for that process to finish safely. Export and import reports live in the run's `ue-exports` and the project's `Saved/GS4DImport`.

The included GS4DTest project is a minimal source build host. It contains no playback map, production asset, imported animation or engine binaries. Create a level after building and importing your own result.

## Representation and limits

The exporter evaluates the trained deformation network at captured timestamps. UE receives animated Gaussian attributes, not the PyTorch model. The player holds each sample until the next timestamp; it does not interpolate the neural field at arbitrary times. Translation, full anisotropic covariance, opacity, and degree 0–3 spherical harmonics are retained. Directional color is evaluated for each view. Captured lighting and shadows remain baked into the model; the player does not reconstruct geometry, fix floating artifacts, or provide physical refraction or dynamic shadow casting.

Coordinates map normalized HUST `(X,Y,Z)` to UE `(X,-Y,Z)*100`. One normalized unit is treated as one meter; this is not restoration of original DCC world scale. Adjust the actor scale if necessary.

This first runtime uses CPU projection and depth sorting with translucent Gaussian quads. Animation data is fully resident, and each frame rebuilds the render proxy. The asset limit is 1.5 GB and 500,000 points. The material converts display-encoded trained colors to linear light for Unreal. Vertex color/opacity quantization, Gaussian footprint truncation, UE transparency, exposure and tone mapping mean results are not pixel-identical to HUST. Multiple Gaussian actors are not globally interleaved by splat depth.

Desktop editor import and playback are the initial validation targets. VR stereo correctness, headset frame rate, packaged builds, streaming, mobile rendering and production performance are not certified. This version establishes a working owned import/playback path; it is not yet evidence of lower VR cost than the original effect.

## File format

Little-endian header: 8-byte `GS4D001\0`, uint32 version (1), point count, frame count, SH degree, float32 source FPS, float32 duration. Then float32 normalized timestamps and frame-major point records of 58 float32 values: position (3), symmetric covariance `(xx,xy,xz,yy,yz,zz)` (6), activated opacity (1), coefficient-major RGB SH (48). SH directions use the original HUST basis. A companion JSON records provenance and SHA-256.

## Building

Build `GS4DTestEditor Win64 Development` with the installed engine's `Engine/Build/BatchFiles/Build.bat` and the test `.uproject`. The plugin source belongs under that project's `Plugins/GS4D`. Copy the resulting `UnrealEditor-GS4D.dll`, `UnrealEditor-GS4DEditor.dll`, and `UnrealEditor.modules` into the canonical `GS4D/Binaries/Win64` for workbench deployment. The workbench verifies the engine BuildId before installing.


## Compile this source archive

1. Copy `unreal/GS4D` to `unreal/GS4DTest/Plugins/GS4D` (or into your own C++ project's Plugins folder).
2. Generate project files with your installed UE 5.8 engine and build GS4DTestEditor in Win64 Development. Install Visual Studio's Unreal C++ prerequisites first.
3. For example, from PowerShell at the repository root (adjust the engine path):

```powershell
New-Item -ItemType Directory -Force unreal/GS4DTest/Plugins
Copy-Item -Recurse unreal/GS4D unreal/GS4DTest/Plugins/GS4D
& 'C:/Program Files/Epic Games/UE_5.8/Engine/Build/BatchFiles/Build.bat' GS4DTestEditor Win64 Development "$(Resolve-Path unreal/GS4DTest/GS4DTest.uproject)" -WaitMutex
```

4. Copy `UnrealEditor-GS4D.dll`, `UnrealEditor-GS4DEditor.dll` and `UnrealEditor.modules` from the built project plugin's `Binaries/Win64` into `unreal/GS4D/Binaries/Win64`.
5. Open **UE Plugin** in the desktop. Select the target project and engine; its exact BuildId must match. Close Unreal Editor, install the plugin, then import a saved model using **Add to Unreal...**.

Do not publish your engine installation or imported user assets with this source repository. Runtime shipping, VR and alternate engine versions need additional validation.
