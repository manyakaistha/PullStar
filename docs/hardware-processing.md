# Hardware-aware processing

The default **Automatic** processing mode uses a bounded CPU frame pool and a compatible OpenCL GPU for automatic star-field trail rendering. **Processing hardware** in the source settings offers a **CPU only** override. Expanded processing activity reports the device and worker count actually used, including fallback reasons.

## Work distribution

- Source decoding and independent star extraction run in exposure order through up to four CPU workers. CPU count, image dimensions, RAW buffer estimates, and a quarter-of-RAM worker budget cap concurrency. OpenCV's native thread count is limited to avoid multiplying a full-machine thread pool by every worker.
- Matching fields, fitting the smooth sky trajectory, and stateful reference tracking retain their sequential dependencies. Detection coordinates are unchanged by parallel extraction.
- Automatic field rendering uses GPU Lanczos-4 warps, foreground-mask multiplication, lighten/additive accumulation, and synthetic trail warps. Decoded frames are prefetched by CPU workers. Aligned frames and the accumulator stay on the GPU between steps; source, map, and scratch buffers are reused, while readback is used only for exports, video frames, foreground segmentation, and recovery checkpoints.
- Manual-reference rendering keeps decoding, float conversion, and Lanczos crop warps in the bounded worker queue; the main thread performs ordered blending and progress/checkpoint I/O. CPU warps retain per-worker remap buffers and use an exact slice for integer translations. Its FFT ghost generator streams one frame at a time instead of retaining an entire ghost batch.
- Display previews calculate their tone scale from a small downsampled sample, and checkpoint cadence expands for very large accumulators. These keep optional UI and recovery I/O from dominating the stack loop without changing the final TIFF.

The GPU sampler uses the same 1/32-pixel interpolation grid and affine-coordinate rounding as CPU OpenCV Lanczos-4. Each initialized device must pass a CPU/GPU image-quality check before rendering. Buffers are checked against device allocation limits and a memory budget. Small automatic renders below one megapixel use the CPU to avoid setup overhead.

If no usable driver is present, initialization or the quality check fails, or memory is insufficient, rendering uses the CPU. If a GPU fails during a render, the staged render is discarded and replayed on the CPU before publication. The action remains cancellable while replaying. Cancelling waits for in-flight CPU workers and the current native/GPU operation to finish, then releases the renderer; it does not publish a partial final TIFF or video.

## Device support and limits

| Device/API | Implementation and verification |
| --- | --- |
| Apple silicon GPU | OpenCL GPU path tested on Apple M4, 10 GPU cores, 16 GB unified RAM. |
| Intel Iris/HD/Xe integrated graphics | Uses a compatible vendor OpenCL driver. No Intel GPU was available for physical validation. |
| NVIDIA GPU, including CUDA-capable models | Uses its OpenCL driver. No NVIDIA GPU was available for physical validation. |
| Other OpenCL GPUs, such as AMD | Discovered through the runtime and checked before use; not physically validated here. |
| Native CUDA, MPS/Metal, Intel XPU | Dedicated native backends are not implemented. GPU execution uses OpenCL, not these APIs. |

GPU availability is determined by a working runtime/compiler, not a GPU brand name. See [PyOpenCL's driver requirements](https://documen.tician.de/pyopencl/misc.html#installation) and [Intel's OpenCL runtimes](https://www.intel.com/content/www/us/en/developer/articles/tool/opencl-drivers.html). The app does not install or replace system graphics drivers.

Apple [deprecates OpenCL and recommends Metal/MPS](https://developer.apple.com/opencl/). The tested M4 currently exposes a working OpenCL GPU, but this does not guarantee support on future macOS versions. If the driver is unavailable, the CPU path remains usable. An MPS blending experiment was slower than CPU blending here, so an MPS path that only blends arrays was not shipped as an acceleration feature.

RAW development, Photutils source measurements, pattern matching, checkpoint compression, and TIFF encoding remain CPU work. GPU processing cannot add support for a RAW encoding that LibRaw cannot decode. Speedups depend on image size, driver, memory, storage, and how much of a job is GPU-eligible. GPU video readback and large checkpoints can reduce the gain.

`GET /api/system/compute` reports CPU/RAM and discovered GPUs. Job requests accept `compute_backend: "auto" | "cpu" | "opencl"` and an optional `cpu_workers` upper bound; the hardware/memory cap still applies. Windows, macOS, and Linux virtual-environment launcher paths have unit coverage; only macOS was tested end to end.

## Validation on supplied photographs

Tested October 22, 2026 in a fresh Python 3.11 environment from `uv.lock`, using pyopencl 2026.1.4 and the Apple M4 OpenCL 1.2 GPU. Each row uses the first twelve photos from the longest consistent JPEG burst in its supplied collection, with 1.5× trail extension and two synthetic frames per interval.

| Collection and dimensions | CPU workers | Serial / parallel extraction | CPU / GPU rendering |
| --- | ---: | ---: | ---: |
| Samsung, 8160 × 6120 | 3 | 14.618 s / 7.750 s | 17.243 s / 7.675 s |
| March 2023, 4080 × 3072 | 4 | 14.377 s / 6.587 s | 4.283 s / 1.995 s |
| April 2026, 4080 × 3060 | 4 | 14.084 s / 6.366 s | 4.288 s / 2.010 s |

Parallel extraction returned identical source coordinates for every tested photo. CPU/GPU rendering reused the same fitted motion so the comparison isolates rendering, rather than randomized matching. All TIFFs were readable and nonempty; CPU/GPU exports differed by at most one 8-bit brightness level. Separate GPU tests cover 16-bit exports, masked synthetic frames, additive blending, checkpoint restoration, resource cleanup, and cancellation. Source SHA-256 hashes were unchanged.

The final implementation passed 112 Python tests (including physical GPU tests on this M4) and 11 client/launcher tests. Native browser requests were used to cancel detection, alignment, and GPU trail creation on a 24-photo real sequence, then restart detection and complete a GPU alignment successfully. Processing activity reported the Apple M4 GPU and four CPU workers. The production UI build also passed.

These local sequential timings include decoding and I/O/cache effects and are not performance guarantees. Serial/parallel extraction and CPU/GPU rendering are separate comparisons, not claimed whole-job speedups. The three data sets' twelve accepted frames in this run do not imply that acceleration improved matching accuracy; robust matching can vary between runs.

Reproduce from the repository root:

```bash
uv sync --group dev --frozen
uv run --group dev pytest -q
uv run python scripts/validate_compute.py \
  --data-dir ../naman-test-data --samples 12 \
  --output-dir /tmp/staraligner-compute-validation
cd frontend
npm ci
npm test
npm run build
```

Reports, temporary input links, TIFFs, and sample previews are written outside the source collection. The report identifies the actual backend, CPU worker count, timings, coordinate equality, output differences, and source hashes. On a machine without a usable GPU the same script records CPU fallback; it must not be interpreted as GPU hardware validation.
