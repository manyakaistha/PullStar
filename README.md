<p align="center">
  <img src="frontend/public/app-icon.png" width="112" height="112" alt="PullStar — tapered white star trails on a dark tile">
</p>

<h1 align="center">PullStar</h1>

<p align="center"><strong>Align the night. Keep the motion.</strong></p>
<p align="center">Steadier exposures. Smoother star trails. Your workflow.</p>

<p align="center">
  <a href="https://github.com/manyakaistha/PullStar/actions/workflows/ci.yml"><img src="https://github.com/manyakaistha/PullStar/actions/workflows/ci.yml/badge.svg?branch=main" alt="Continuous integration"></a>
  <a href="https://github.com/manyakaistha/PullStar/releases/latest"><img src="https://img.shields.io/github/v/release/manyakaistha/PullStar?label=release&amp;color=7d9d93" alt="Latest release"></a>
  <a href="#get-pullstar"><img src="https://img.shields.io/badge/macOS-14%2B%20%C2%B7%20Apple%20Silicon-333333?logo=apple&amp;logoColor=white" alt="macOS 14 or later, Apple Silicon"></a>
</p>

<p align="center">
  <a href="https://www.electronjs.org/"><img src="https://img.shields.io/badge/Electron-47848F?style=flat-square&amp;logo=electron&amp;logoColor=white" alt="Electron"></a>
  <a href="https://react.dev/"><img src="https://img.shields.io/badge/React-20232A?style=flat-square&amp;logo=react&amp;logoColor=61DAFB" alt="React"></a>
  <a href="https://www.typescriptlang.org/"><img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&amp;logo=typescript&amp;logoColor=white" alt="TypeScript"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&amp;logo=fastapi&amp;logoColor=white" alt="FastAPI"></a>
  <a href="https://tailwindcss.com/"><img src="https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat-square&amp;logo=tailwindcss&amp;logoColor=white" alt="Tailwind CSS"></a>
</p>

<p align="center">
  <a href="https://github.com/manyakaistha/PullStar/releases/latest"><strong>Download for macOS</strong></a> &nbsp;·&nbsp;
  <a href="#your-first-session">Quick start</a> &nbsp;·&nbsp;
  <a href="#mcp-integration">MCP setup</a> &nbsp;·&nbsp;
  <a href="#technology-stack">Technology stack</a>
</p>

<p align="center">
  <img src="docs/images/workspace.png" alt="PullStar’s dark alignment workspace, with a large image viewfinder, frame sequence, processing activity, and export settings">
  <br>
  <sub>The alignment studio. Preview your frames, choose your workflow, and follow processing in one workspace.</sub>
</p>

A night-sky sequence can capture hours of beautiful motion—and every small movement of the camera. PullStar corrects camera wobble while preserving the sky’s natural rotation, so your stars keep their trails.

Export the aligned exposures to your preferred editor, or create a trail image and trail-lapse video in PullStar. Processing runs locally on your computer; no account or cloud upload is required.

## Choose your finish

| What you want | What PullStar exports |
| :--- | :--- |
| **Steadier frames for another editor** | An aligned TIFF, PNG, or JPEG sequence with a common crop. Skip trail creation entirely. |
| **A finished star-trail image** | A TIFF, PNG, or JPEG stack, with optional gap filling and synthetic trail extension. |
| **A trail-lapse video** | MP4 or MOV, with H.264, HEVC, lossless H.264, or ProRes options. ProRes uses MOV. |

TIFF and PNG retain 16-bit data when the processing path provides it. JPEG is 8-bit. RAW inputs are developed into pixels; exports are not camera RAW or DNG files. See the [export workflow](docs/export-workflow.md) for format and destination details.

## Made for the night sky

- **Polaris is optional.** Automatic alignment matches the stellar field, including sequences with the celestial pole outside the image. Manual reference tracking is available when you need it.
- **Keep natural sky motion.** Correct the camera’s wobble while retaining the rotation that creates trails.
- **Work with your exposures.** View JPEG, PNG, TIFF, and supported camera RAW files, with zoom, reference selection, and a frame filmstrip.
- **Shape the result.** Preserve the foreground, fill timestamp gaps, and optionally extend or taper synthetic trails. Synthetic frames model motion; they do not recover missing observed detail.
- **Control the workload.** Choose image and video resolutions, use memory-bounded CPU processing or supported OpenCL acceleration, and cancel active work from the workspace.
- **Automate the workflow.** Use the included MCP server to inspect a sequence, compare settings, render previews, and manage exports.

## Get PullStar

The current desktop release supports **Apple Silicon Macs running macOS 14 or later**. Python, FFmpeg, and the processing libraries are bundled in the installer.

1. Download the **[latest macOS DMG](https://github.com/manyakaistha/PullStar/releases/latest)**.
2. Open it and drag **PullStar** into **Applications**.
3. Launch PullStar and choose your exposure folder.

> [!IMPORTANT]
> The current release is **ad-hoc signed and not Apple-notarized**. macOS may block its first launch. If you trust the downloaded release, use **System Settings → Privacy & Security → Open Anyway** after the first launch attempt.

<details>
<summary><strong>Verify the download and check compatibility</strong></summary>

Download `SHA256SUMS.txt` from the same release and compare its DMG entry against:

```bash
shasum -a 256 PullStar-1.0.1-macOS-arm64.dmg
```

The packaged app has been tested on macOS 27.0.1. Intel Macs and other desktop platforms require a source installation; separate installers have not been validated.

Camera RAW support depends on the encoding supported by LibRaw/rawpy. An embedded DNG preview can display even when the underlying RAW pixels cannot be decoded for alignment or export. See [DNG support](docs/dng-viewing.md).

</details>

## Your first session

1. **Load your sequence.** Select **Load frames** and choose the folder containing your exposures.
2. **Choose alignment.** Use automatic star-field matching, or select manual reference stars in the viewfinder.
3. **Choose your output.** Select **Aligned images only** to continue in another editor, or choose star trails with optional frame and video export. Set your format and destination.
4. **Process and review.** Start the job, follow its progress, and review the output paths in **Results**. Active processing can be cancelled.

For RAW development, output bit depth, shared cropping, and export destinations, read the [image and video export guide](docs/export-workflow.md).

## Technology stack

The interface runs in Electron. A local Python service handles image processing and sends progress to the workspace over WebSockets. The MCP server exposes the processing engine to compatible automation clients.

| Layer | Technologies and purpose |
| :--- | :--- |
| **Desktop & interface** | **Electron · React · TypeScript** — desktop shell, native folder selection, and the alignment workspace. |
| **Styling & interaction** | **Tailwind CSS · Framer Motion · Lucide** — styling, motion, and interface icons. |
| **Local API** | **Python · FastAPI · Pydantic · Uvicorn · WebSockets** — validated job requests, background processing, and live progress. |
| **Astronomy** | **Photutils · Astroalign · Astropy** — star detection, field matching, and astronomical calculations. |
| **Images & scientific computing** | **NumPy · SciPy · OpenCV · scikit-image · Pillow** — transforms, filtering, blending, previews, and image export. |
| **RAW development** | **rawpy · LibRaw** — supported camera RAW decoding and embedded previews. |
| **Acceleration & video** | **PyOpenCL · FFmpeg** — optional GPU processing and video encoding, with CPU fallback for image processing. |
| **Automation** | **MCP Python SDK** — tools, resources, and prompts over stdio, SSE, and Streamable HTTP. |
| **Build & distribution** | **Vite · uv · npm · PyInstaller · Electron Builder** — frontend builds, dependency management, standalone Python bundling, and the macOS DMG. |

Exact dependency versions are recorded in [`frontend/package-lock.json`](frontend/package-lock.json) and [`uv.lock`](uv.lock). Release assets include a dependency inventory and [third-party notices](THIRD_PARTY_NOTICES.md).

## MCP integration

PullStar includes **15 MCP tools** for sequence inspection, star analysis, settings recommendations, alignment comparisons, previews, quality evaluation, exports, and background jobs. The server ships in this repository’s `main` branch and inside the macOS app.

Add this entry to your MCP client configuration after installing PullStar in **Applications**:

```json
{
  "mcpServers": {
    "pullstar": {
      "command": "/Applications/PullStar.app/Contents/Resources/backend/pullstar-backend",
      "args": ["--mcp"]
    }
  }
}
```

No separate Python installation is needed for the bundled server. For a source checkout, run:

```bash
uv --directory /absolute/path/to/PullStar run pullstar-mcp
```

See the [MCP guide](docs/mcp-server.md) for transports, tool arguments, and example workflows, or adapt [`mcp.json.example`](mcp.json.example). The legacy `star-aligner-mcp` command and `staraligner://` resource URIs remain available for client compatibility. Connect trusted clients; see the [security policy](SECURITY.md).

## Run from source

Use **Python 3.11**, [uv](https://docs.astral.sh/uv/), **Node.js 24 LTS** (or a supported Node.js 22.12+ installation), and npm. Install FFmpeg separately for source-based video export.

```bash
git clone https://github.com/manyakaistha/PullStar.git
cd PullStar
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend start
```

For live frontend development, use `npm --prefix frontend run desktop`. For command-line processing:

```bash
uv run python main.py --input /path/to/exposures --auto --output /path/to/trails.tiff
```

The [CLI guide](docs/cli-guide.md) covers aligned-image export, video formats, and processing options. The [frontend guide](frontend/README.md) explains browser development and the desktop shell.

<details>
<summary><strong>Development checks and installer builds</strong></summary>

Run from the repository root, with FFmpeg available for video integration tests:

```bash
uv run pytest -q
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

To build the standalone macOS installer on Apple Silicon:

```bash
uv run python scripts/build_backend.py
npm --prefix frontend run package:mac
```

The DMG is written to `release/`. See [release engineering](docs/releases.md) for packaging, signing, and validation. The [1.0.0 validation report](docs/release-validation.md) records the application tests and installed-app checks performed for the release.

</details>

## Explore the documentation

| Guide | What it covers |
| :--- | :--- |
| [Automatic alignment](docs/automatic-star-alignment.md) | Star-field matching, motion correction, and algorithm validation. |
| [Image & video exports](docs/export-workflow.md) | Images-only workflows, formats, bit depth, and destinations. |
| [RAW recovery](docs/noisy-raw-recovery.md) · [DNG viewing](docs/dng-viewing.md) | Dim exposures, RAW processing, and camera-preview limitations. |
| [Hardware & performance](docs/hardware-processing.md) | CPU workers, OpenCL support, and measured performance. |
| [MCP server](docs/mcp-server.md) · [CLI](docs/cli-guide.md) | Automation, settings, previews, and processing commands. |

Found a problem? [Open an issue](https://github.com/manyakaistha/PullStar/issues) with your PullStar version, operating system, input format, and steps to reproduce. For security concerns, follow [SECURITY.md](SECURITY.md). Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change.

## Ownership & licensing

The original PullStar code and artwork are **copyright © 2026 Manya Kaistha, all rights reserved**. This repository is public for inspection; no open-source license is granted. See [LICENSE](LICENSE).

Bundled dependencies retain their own licenses. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [COPYING](COPYING) describe the applicable third-party terms.
