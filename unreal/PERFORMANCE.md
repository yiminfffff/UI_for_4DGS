# Whole-scene desktop playback

Measured on **22 October 2026** with the GPU player and continuous interpolation enabled. The headline figures describe the final overall UE frame, including the scene, player, lights, post-processing and HUD. They are not FPS inferred from an isolated compute or rasterizer GPU timing.

## Conditions

- UE 5.8.2, build 56702186; standalone Development, desktop single view.
- NVIDIA GeForce RTX 4090 Laptop GPU; 1280 × 720, D3D12, VSync disabled, no FPS cap.
- Same explosion: all 8,133 Gaussians, 12 baked samples, full SH, `MaxPoints = 0`.
- Original `.gs4d` export: 22,642,352 bytes (21.59 MiB); no larger bake or point reduction.
- The source samples span 1.375 seconds, at eight sample intervals per second. Current playback adds a 0.125-second final hold, for a 1.5-second effect.

## Final overall frame rate

| Scene and workload | Mean FPS | Mean whole-frame time | P95 frame time | Timed window |
| --- | ---: | ---: | ---: | --- |
| Blast empty scene, normal explosion playback | **475.99** | 2.101 ms | 2.736 ms | 5,712 frames / about 12 s |
| Trench gameplay scene, Q explosion and authored flash/fire lights | **115.26** | 8.676 ms | 11.051 ms | 173 frames / 1.501 s |

FPS is the measured frame count divided by summed game-frame time. It is not an arithmetic mean of instantaneous FPS readings. P95 describes the 95th percentile of frame duration.

Blast's five phases each warm up before a 12-second measurement. The normal playback, moving-camera and close-up phases all run the animation. Their camera coverage differs.

| Blast phase | Overall FPS | Mean frame time | P95 frame time |
| --- | ---: | ---: | ---: |
| Static interpolated state | 513.74 | 1.947 ms | 2.538 ms |
| Playback | 475.99 | 2.101 ms | 2.736 ms |
| Moving camera | 458.32 | 2.182 ms | 2.751 ms |
| Close-up playback | 489.62 | 2.042 ms | 2.662 ms |
| Hidden effect baseline, asset remains loaded | 554.29 | 1.804 ms | 2.249 ms |

The trench result uses the third uninterrupted Q playback, after warmup and movement, jump, mouse and restart checks. The camera is stationary during the timed effect. The whole scene and authored explosion lights are active, but no screenshot is saved inside that timing window. First-playback and aggregate validation timings include synchronous image-saving stalls and are excluded from the normal-playback headline.

The trench timing window is much shorter than Blast's. It is a short effect test, not a sustained gameplay average, and the two scene results are not equal-duration benchmarks. There is no matching old-version trench benchmark from which to calculate an improvement percentage.

## What changed

The old player held the last baked sample, so this asset's motion changed only about eight times per second even when viewport FPS was high. The current player interpolates stable IDs between adjacent samples on each rendered frame, including position, covariance, opacity and SH coefficients. UE still plays a baked approximation rather than running Workbench's neural deformation network.

GPU compute now generates projected anisotropic quads and full SH colors in persistent buffers. Source attributes upload once per scene proxy; playback updates the render-thread time without rebuilding the proxy. CPU sorting uses interpolated positions and updates the draw indices. The existing translucent material, exposure, fog and scene-occlusion path remain in use.

A fresh same-condition Blast run with the old CPU player measured 282.65 FPS for normal playback (3.538 ms mean), compared with 475.99 FPS (2.101 ms) for the GPU player with interpolation enabled: a 40.6% reduction in whole-frame duration in this single-machine comparison. The hidden-effect baseline varied by about 2.5%. An older October 19 result around 38 FPS did not reproduce and is not used as the upgrade baseline.

## Checks and limits

- Input and playback checks passed in both demos. Trench checks covered colliding spawn, movement, jumping, mouse look, Q restart, one-shot stop, hidden state and lights off.
- The clean trench playback reached all 12 source sample indices, recorded 159 requested animation times and 147 within-sample interpolation-alpha changes. This is requested-state evidence sharing the render selection math, not GPU image readback.
- At the same fixed camera and baked sample with interpolation disabled, the GPU/old-CPU screenshot foreground comparison measured PSNR 57.53 dB, mean absolute difference 0.115/255, maximum difference 2/255 and the same thresholded image bounds. This supports that tested view and sample rather than pixel identity across all viewpoints.
- Scene complexity, camera coverage, power and thermal conditions affect results. Single original-machine runs do not establish fixed performance on other systems.
- Workbench normally previews at 512 × 512 and uses a different neural/CUDA/UI pipeline. Its isolated CUDA timing cannot be directly compared with the complete UE frame.
- Packaged Shipping builds, headset stereo frame rate, VR correctness, mobile rendering and streaming were not validated by these tests.

The repository includes source and a [sanitized measurement summary](benchmarks/desktop-2026-10-22.json). The tested effects, UE levels, Megascans assets, screenshots and private run data are excluded. See [build and demo-runtime instructions](README.md) to use the code with your own content.
