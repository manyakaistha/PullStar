# Third-party notices

PullStar includes components with their own copyright and license terms. Their licenses continue to apply. The release includes a dependency inventory; Python distribution license metadata is retained in the backend where available. Electron includes `LICENSE.electron.txt` and `LICENSES.chromium.html` in the application bundle.

- **Electron / Chromium / Node.js**: MIT and the component licenses shipped with Electron.
- **React, Vite, TypeScript, Lucide, Framer Motion, Radix, Tailwind utilities**: predominantly MIT/ISC; see the locked npm dependencies and their package license files.
- **Python**: Python Software Foundation License.
- **NumPy, SciPy, Astropy, Photutils, scikit-image, Matplotlib, Pillow, FastAPI, Uvicorn, MCP SDK, PyOpenCL, and related dependencies**: their respective BSD, MIT, PSF, HPND, and other distribution licenses. Consult the included dependency inventory and upstream distributions.
- **rawpy / LibRaw**: rawpy is MIT; LibRaw is LGPL-2.1/CDDL dual licensed. Upstream source: https://github.com/letmaik/rawpy and https://github.com/LibRaw/LibRaw .
- **FFmpeg 7.1**: the bundled macOS arm64 executable is supplied by imageio-ffmpeg 0.7.0 and was compiled with `--enable-gpl`, libx264, and libx265. FFmpeg is GPL-licensed in this configuration. License: https://ffmpeg.org/legal.html . FFmpeg source: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz . Binary packaging and build recipes: https://github.com/imageio/imageio-ffmpeg and https://github.com/imageio/imageio-binaries . Related codec source: https://code.videolan.org/videolan/x264 and https://bitbucket.org/multicoreware/x265_git .
- **PyInstaller**: GPL with its bootloader exception; building an application does not by itself impose the PyInstaller GPL on that application.

The application’s source and build scripts are available at https://github.com/manyakaistha/PullStar . Bundled third-party libraries retain their upstream notices and license obligations. Do not remove these notices when redistributing a build.
