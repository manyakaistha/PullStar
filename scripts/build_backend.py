"""Build the standalone native Python service, including a portable FFmpeg."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]


def main():
    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    staged = ROOT / "build" / "ffmpeg" / "ffmpeg"
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ffmpeg, staged)
    staged.chmod(0o755)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--name", "pullstar-backend", "--onedir", "--console",
        "--distpath", str(ROOT / "build" / "backend"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"), "--paths", str(ROOT),
        "--add-binary", f"{staged}{os.pathsep}bin",
        "--collect-submodules", "backend", "--collect-submodules", "mcp_server",
        "--collect-all", "photutils", "--collect-all", "astroalign",
        "--collect-all", "rawpy", "--collect-all", "pyopencl",
        "--collect-data", "astropy", "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto", "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto", "--hidden-import", "uvicorn.lifespan.on",
        "--exclude-module", "pytest", "--exclude-module", "IPython",
        "--exclude-module", "tkinter", str(ROOT / "backend" / "desktop_entry.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "collect_licenses.py")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
