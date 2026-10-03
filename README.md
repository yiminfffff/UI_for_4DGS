# 4DGS Workbench

A local Windows desktop workflow for capturing animated effects in Maya or Houdini, training HUST 4DGaussians, inspecting the result in an interactive 3D viewer, and baking animation for a project-owned Unreal Engine player.

**Source release / experimental toolchain.** All application UI, messages and authored code comments are in English. Python environments, upstream HUST sources, scene assets, trained models and engine binaries are not bundled.

## Features

- Maya 2027 / Arnold and Houdini 22.0.368 / Solaris-Karma capture panels.
- Sixteen fixed cameras, shared animation samples, RGBA PNG sequences and exact camera/time metadata; fourteen training cameras and two held-out cameras by default.
- Dataset validation, presets, saved run configuration, safe stop and checkpoint resume.
- Horizontal settings above side-by-side source-sequence and 4DGS previews.
- In-memory live preview from initialized point clouds through coarse/fine training. Updates are coalesced between iterations and add some training overhead.
- Maya-style Alt-drag navigation, animation playback and a **Match Source Camera** toggle.
- Independent GPU detection, training-environment checks/extension repair and project-plugin checks/install.
- Video export and a self-authored Unreal GS4D editor/runtime plugin with animation baking/import.

## Tested targets

| Component | Local validation target |
| --- | --- |
| OS | Windows, 64-bit |
| GPU | NVIDIA RTX 4090 Laptop, 16 GB; CUDA architecture 8.9 |
| Training | Python 3.10, PyTorch 2.7.1+cu128, CUDA toolkit 12.8 |
| Desktop | PySide6 Essentials 6.8.3, Pillow 11.3.0 |
| Maya | Maya 2027 with bundled Arnold |
| Houdini | Houdini 22.0.368, Python 3.13, Solaris/Karma |
| Unreal | UE 5.8.2 editor; compile GS4D for the exact installed engine |

Other GPUs, compiler versions and operating systems need separate validation. This source archive does not include a preconfigured CUDA environment.

## Get started

1. Extract or clone the complete repository to a stable folder, such as `C:\4DGS`. Keep the capture plugins beside `workbench`.
2. Follow [INSTALL.md](INSTALL.md) to obtain the pinned HUST backend and set up the training and desktop environments.
3. Run `start-workbench.cmd` and check **Training Environment**. Verify a small dataset with **Smoke Test** before a production run.
4. Install either [Maya capture](maya-gs-capture/README.md) or [Houdini capture](houdini-gs-capture/README.md), create cameras and export a complete dataset.
5. Open it in the workbench, train, inspect and export. See [Workbench guide](workbench/README.md).
6. To use Unreal, first [build GS4D](unreal/README.md), then use **UE Plugin** to install it and **Add to Unreal...** to bake/import a result.

Capture plugins can run without the training environment. The desktop can also be set up with a separate Python 3.10 installation; see INSTALL.md.

## Repository layout

```text
workbench/                 Desktop UI, training adapter, live renderer and exporters
maya-gs-capture/           Maya / Arnold capture panel and tests
houdini-gs-capture/        Solaris / Karma capture panel and tests
unreal/GS4D/              Owned Unreal editor/runtime plugin source
unreal/GS4DTest/           Minimal source project for compiling the plugin
backend-overrides/        Optional local smoke/preview configurations
windows-compat.patch      Changes against the pinned upstream HUST source
conda-windows-explicit.txt Reference training environment manifest
```

## Limits

The workbench reconstructs captured appearance. Lighting, shadows and background are baked; successful training does not imply clean geometry, physically correct refraction or production fluid/fracture quality. Opacity resets can temporarily produce a pale live preview; the viewer shows the actual current model.

UE receives sampled, baked Gaussian animation rather than the neural network. The initial player uses CPU projection/depth sorting and translucent quads, holds samples between timestamps, and does not establish a VR performance advantage. Headset stereo, packaged games, streaming and mobile performance require further work.

The archive contains no user captures, production models, DCC scenes, private run history, credentials or Python/engine installations. A fresh machine installation has not been verified from this archive; existing-machine integration and focused regression tests are recorded in [VALIDATION.md](VALIDATION.md).

## Attribution and licensing

The backend is [HUST 4DGaussians](https://github.com/hustvl/4DGaussians), pinned to `843d5ac636c37e4b611242287754f3d4ed150144`. Obtain dependencies from their original sources and retain their license terms. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

No license has been selected for the original workbench/capture/player code in this source release. Public availability does not by itself grant an open-source license. The repository owner can select a license separately; upstream licenses remain applicable to upstream material.
