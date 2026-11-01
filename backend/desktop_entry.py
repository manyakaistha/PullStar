"""Standalone desktop service and bundled MCP entry point."""
from __future__ import annotations

import argparse
import multiprocessing
import os
from pathlib import Path
import socket
import sys


def main() -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(prog="pullstar-backend")
    parser.add_argument("--mcp", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args, remaining = parser.parse_known_args()
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    binaries = bundle / "bin"
    if binaries.is_dir():
        os.environ["PATH"] = str(binaries) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("MPLBACKEND", "Agg")
    if args.mcp:
        # Third-party image-processing progress belongs on stderr, not MCP stdout.
        from mcp_server.server import main as run_mcp
        run_mcp(remaining)
        return
    if remaining:
        parser.error("unrecognized arguments: " + " ".join(remaining))
    import uvicorn
    from backend.main import app
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", args.port))
        listener.listen(128)
        print(f"PULLSTAR_BACKEND=http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])


if __name__ == "__main__":
    main()
