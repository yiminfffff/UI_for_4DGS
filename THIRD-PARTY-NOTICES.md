# Third-party notices

Original workbench, capture and GS4D player source has no selected distribution license in this release. Do not infer a permissive license from public hosting.

The archive does not bundle upstream HUST code, CUDA extensions, Python wheels, DCC applications, Unreal Engine, datasets or trained models. Obtain them separately and consult their own licenses and applicable usage terms.

| Dependency | Source / provenance |
| --- | --- |
| HUST 4DGaussians | https://github.com/hustvl/4DGaussians ; commit 843d5ac636c37e4b611242287754f3d4ed150144 ; upstream LICENSE.md is Apache-2.0 |
| depth-diff-gaussian-rasterization | https://github.com/ingra14m/depth-diff-gaussian-rasterization ; HUST gitlink e49506654e8e11ed8a62d22bcb693e943fdecacf |
| simple-knn | https://gitlab.inria.fr/bkerbl/simple-knn ; HUST gitlink 44f764299fa305faf6ec5ebd99939e0508331503 |
| GLM | https://github.com/g-truc/glm ; obtained through the rasterizer submodule |
| PyTorch / torchvision | https://pytorch.org ; dependencies installed separately |
| PySide6 / Qt | https://doc.qt.io/qtforpython-6/ ; separate desktop dependencies |
| Pillow and other Python packages | Their respective upstream distributions; see requirements files |
| D-NeRF sample | Original dataset endpoint used by download_sample.py; data excluded |
| Maya / Arnold | Autodesk application/runtime supplied by the user |
| Houdini / Karma | SideFX application/runtime supplied by the user |
| Unreal Engine | Epic Games engine/toolchain supplied by the user |

windows-compat.patch contains changes and surrounding excerpts from the pinned HUST source. The original HUST LICENSE.md is reproduced in licenses/HUST-Apache-2.0.txt for that upstream material; it does not license the original tools in this archive. No blanket license is claimed for the CUDA rasterizer or KNN submodules.
