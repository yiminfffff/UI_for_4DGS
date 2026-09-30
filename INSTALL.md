# Windows installation

Use a stable folder such as `C:\4DGS`. Run commands from that folder. These steps reproduce the tested dependency choices; a clean-machine install of this publication archive is not yet validated. Do not upgrade or replace a working local environment just to follow this guide.

## 1. Desktop without the training backend

Install Python 3.10 for Windows if needed, then run:

```powershell
py -3.10 -m venv .envs/workbench
.envs/workbench/Scripts/python.exe -m pip install -r workbench/requirements.txt
.\start-workbench.cmd
```

This opens the desktop, source inspector and maintenance panels. Training and model rendering still require section 2. The capture plugins use their DCC application's bundled Python and need neither environment.

## 2. Training backend

Install Git, a Conda-compatible environment manager, an NVIDIA driver compatible with CUDA 12.8 and Visual Studio 2022 Build Tools with the C++ workload. The tested compiler was MSVC 14.44. PyTorch's CUDA runtime alone does not supply the compiler needed to build extensions.

Fetch the exact upstream version and only the rendering submodules:

```powershell
git clone https://github.com/hustvl/4DGaussians.git HUST-Windows
git -C HUST-Windows checkout 843d5ac636c37e4b611242287754f3d4ed150144
git -C HUST-Windows submodule update --init --recursive submodules/depth-diff-gaussian-rasterization submodules/simple-knn
git -C HUST-Windows apply ../windows-compat.patch
```

Do not recursively initialize the optional SIBR viewer. Keep HUST-Windows at this exact path; the worker locates it relative to the repository root. The compatibility patch changes RGB conversion to uint8 and removes an unused Open3D import. It does not replace the reconstruction algorithm.

Create the local environment with the supplied Windows reference manifest:

```powershell
conda create --prefix .envs/hust4dgs --file conda-windows-explicit.txt
.envs/hust4dgs/python.exe -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128
.envs/hust4dgs/python.exe -m pip install torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
.envs/hust4dgs/python.exe -m pip install --no-build-isolation -r requirements-windows.txt
.envs/hust4dgs/python.exe -m pip install psutil
cmd /c build-hust.cmd
```

The manifest includes Python 3.10 and the local CUDA 12.8 toolkit. Package availability, compiler compatibility and GPUs beyond the original machine need verification. The CPU torchvision package supplies image transforms; training/rendering use CUDA PyTorch. If an upstream submodule endpoint is unavailable, obtain its pinned source from the original project; do not substitute an unrelated latest implementation.

**The current build script targets compute capability 8.9.** For another GPU, review CUDA support and every `TORCH_CUDA_ARCH_LIST` setting before compiling. A successful desktop launch does not prove GPU/backend readiness.

If the desktop environment is not already installed, run:

```powershell
powershell -ExecutionPolicy Bypass -File setup-workbench.ps1
```

Open the desktop, use **Training Environment > Check Environment**, and confirm a real CUDA render passes. **Rebuild CUDA Extensions** repairs the compiled extensions in an existing environment; driver/compiler setup is manual. See [Environment maintenance](workbench/ENVIRONMENT-SETUP.md).

## 3. Capture and train

Install the [Maya](maya-gs-capture/README.md) or [Houdini](houdini-gs-capture/README.md) panel. Keep simulations cached, camera poses fixed and lighting/color transforms consistent. Render three previews, then export a complete dataset. Select the dataset in the desktop, validate it, and train a Smoke Test run first. A preview directory is not a complete dataset.

The optional `download_sample.py` fetches the upstream D-NeRF bouncingballs sample using HTTP ranges and CRC validation; it requires `requests` in the interpreter used to run it. No sample data is redistributed here. If its remote archive changes, use the original dataset download instructions instead.

## 4. Unreal

This archive is source-only. Compile GS4D against the exact installed engine before **UE Plugin** can install it. See [Unreal build/install](unreal/README.md). Project checks and plugin installation do not require CUDA or a trained run once the desktop and plugin binaries exist. Model baking does require the training environment and a saved fine-stage snapshot.

## Troubleshooting

- No window: check `.cache/workbench/startup.log`; startup exceptions also produce an English error dialog. Unavailable recent runs are skipped.
- Missing backend: verify `HUST-Windows` and `.envs/hust4dgs/python.exe` exist at the expected paths.
- Missing CUDA extension: verify the local toolkit and Visual Studio C++ tools, then rebuild and recheck.
- UE Incompatible: compile the player for the exact engine BuildId and copy its binaries to the canonical plugin folder.
- Capture export rejected: check the complete manifest, image checksums, fixed cameras and unchanged source assets. Use a new run for changed source data.
