"""Exercise the installed backend through its actual stdio MCP transport."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys
import tempfile

import cv2
import mcp
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_field_alignment import write_sequence


async def check(executable: Path):
    protocol_errors = []
    class ProtocolLog(logging.Handler):
        def emit(self, record):
            if "Failed to parse JSONRPC" in record.getMessage():
                protocol_errors.append(record.getMessage())
    logging.getLogger().addHandler(ProtocolLog())
    with tempfile.TemporaryDirectory(prefix="pullstar-release-") as directory:
        root = Path(directory)
        source = root / "exposures"
        source.mkdir()
        write_sequence(source, dtype=np.uint16)
        params = mcp.StdioServerParameters(
            command=str(executable.resolve()), args=["--mcp"], cwd=directory,
            env={"PATH": "/usr/bin:/bin", "HOME": str(root), "MPLBACKEND": "Agg"},
        )
        async with mcp.Client(params, read_timeout_seconds=120) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            assert {"create_stack", "inspect_sequence", "start_stack_job"} <= tools

            async def call(tool, **arguments):
                result = await client.call_tool(tool, arguments)
                assert not result.is_error, result
                return json.loads(result.content[0].text)

            inspection = await call("inspect_sequence", input_dir=str(source))
            assert inspection["num_images"] == 12
            outputs = []
            for format in ("tiff", "png", "jpg"):
                target = root / f"aligned-{format}"
                result = await call("create_stack", input_dir=str(source), output_file=str(target),
                                    save_frames=True, no_stack=True, image_format=format,
                                    use_checkpoint=False, compute_backend="cpu")
                files = sorted(target.glob(f"*.{format}"))
                assert len(files) == 12, (format, result, list(target.iterdir()))
                image = cv2.imread(str(files[0]), cv2.IMREAD_UNCHANGED)
                assert image.dtype == (np.uint8 if format == "jpg" else np.uint16)
                assert result["quality_report"] is None
                outputs.append(format)
            for quality, container in (("high", "mp4"), ("prores", "mov")):
                target = root / f"trails-{quality}.png"
                result = await call("create_stack", input_dir=str(source), output_file=str(target),
                                    image_format="png", video_enabled=True, video_format=container,
                                    quality=quality, use_checkpoint=False, compute_backend="cpu")
                assert target.is_file(), result
                video = target.with_suffix('.' + container)
                assert video.is_file() and video.stat().st_size > 1000, result
                outputs.append(f"{quality}/{container}")
        assert not protocol_errors, protocol_errors
        print(json.dumps({"passed": True, "tools": len(tools), "formats": outputs}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    asyncio.run(check(parser.parse_args().executable))
