# Training Environment Setup

The workbench uses a project-local HUST backend. A scene is trained from its captured images; no generic pretrained model download is required.

## Existing installation

Click Check Environment. A Ready result verifies the HUST source, deformation network, PyTorch/CUDA, both compiled extensions, and an actual small GPU render. GPU checks and repairs require training to be stopped.

If CUDA extensions fail but Python/PyTorch are installed, click Rebuild CUDA Extensions. This runs the existing build-hust.cmd using Visual Studio Build Tools, the local CUDA toolkit, and the pinned extension source. After completion, click Check Environment again. This rebuild does not upgrade PyTorch or change trained scenes.

## Fresh or incomplete installation

Automatic setup of drivers and compiler prerequisites is not provided by this version. Install NVIDIA's driver and Visual Studio 2022 Build Tools with the C++ workload first. A compatible CUDA compiler is required for building the custom extensions, in addition to PyTorch's CUDA runtime.

Restore the pinned Windows-compatible HUST-Windows source, its submodules and windows-compat.patch. The pinned HUST commit is 843d5ac636c37e4b611242287754f3d4ed150144. A plain latest upstream checkout is not a replacement for this tested backend.

Create the local Python 3.10 / CUDA 12.8 environment at .envs/hust4dgs using the project's conda-windows-explicit.txt manifest and a Conda-compatible installer. These manifests describe the original Windows build; check compatibility before using another GPU or compiler. The extension build currently targets NVIDIA compute capability 8.9.

From the project root, using the installed local Python:

    .envs/hust4dgs/python.exe -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128
    .envs/hust4dgs/python.exe -m pip install torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cpu
    .envs/hust4dgs/python.exe -m pip install --no-build-isolation -r requirements-windows.txt
    .envs/hust4dgs/python.exe -m pip install psutil
    build-hust.cmd

Use Check Environment to verify, then validate a small capture and use Smoke Test before a production run. For the desktop dependencies, setup-workbench.ps1 creates the separate UI environment once the local backend Python exists.

If dependencies are partially broken, repair only the reported missing package using the pinned project requirements. Do not apply the raw freeze file to a new machine: it includes local build paths. Do not overwrite a working environment simply to use a newer package version.

The UE plugin can be checked and installed independently of the HUST training environment. Select a project and matching engine in UE Plugin. The source release requires compiling local GS4D binaries for the exact engine BuildId; an incompatible engine needs a plugin rebuild.

For exact source checkout/submodule commands and the source-only UE build steps, start with [INSTALL.md](../INSTALL.md).
