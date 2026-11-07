#!/usr/bin/env python3
"""
Dump Pass-1 field alignment transforms from Python reference engine.

Matrix Direction:
  Maps source frame pixel coordinates -> reference frame coordinates (source -> reference).
  Given a pixel (x_src, y_src) in frame `frame`, its position in the reference frame
  canvas (before crop) is:
    x_ref = a * x_src + b * y_src + tx
    y_ref = c * x_src + d * y_src + ty

  This matches cv2.warpAffine(frame, matrix, (w, h)) forward mapping convention,
  and FrameTransform in Swift:
    [ a,  b, tx ]
    [ c,  d, ty ]
    [ 0,  0,  1 ]

Output JSON format:
  [
    {
      "frame": 0,
      "a": 1.0,
      "b": 0.0,
      "tx": 0.0,
      "c": 0.0,
      "d": 1.0,
      "ty": 0.0,
      "time": 0.0,
      "skipped": false
    },
    ...
  ]
"""

import argparse
import json
import sys
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.engine.alignment_engine import AlignmentEngine


def main():
    parser = argparse.ArgumentParser(description="Dump Pass-1 transforms from Python engine")
    parser.add_argument("input", nargs="?", help="Input directory containing image sequence")
    parser.add_argument("output", nargs="?", help="Output JSON file path")
    parser.add_argument("-i", "--input-dir", dest="input_opt", help="Input directory (flag option)")
    parser.add_argument("-o", "--output-file", dest="output_opt", help="Output JSON file path (flag option)")
    parser.add_argument("--no-raw-recovery", action="store_true", help="Disable RAW noise reduction")
    args = parser.parse_args()

    input_dir = args.input or args.input_opt
    output_file = args.output or args.output_opt

    if not input_dir or not output_file:
        parser.error("Both input directory and output file must be specified.")

    input_path = Path(input_dir).resolve()
    output_path = Path(output_file).resolve()

    if not input_path.is_dir():
        print(f"Error: Input path is not a directory: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    dummy_output = output_path.parent / ".dummy_output.tiff"
    engine = AlignmentEngine(
        input_dir=input_path,
        output_file=dummy_output,
        raw_noise_reduction=not args.no_raw_recovery,
    )

    try:
        engine.prepare()
        frames, transforms = engine.run_pass1(polaris=None, second_star=None)
        field_analysis = engine.field_analysis

        result = []
        for idx, (t, f) in enumerate(zip(transforms, field_analysis.frames)):
            mat = t.matrix  # 2x3 numpy array
            result.append({
                "frame": idx,
                "a": float(mat[0, 0]),
                "b": float(mat[0, 1]),
                "tx": float(mat[0, 2]),
                "c": float(mat[1, 0]),
                "d": float(mat[1, 1]),
                "ty": float(mat[1, 2]),
                "time": float(field_analysis.times[idx]),
                "skipped": not t.is_valid,
            })

        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Dumped {len(result)} transforms to {output_path}")

    finally:
        engine.cleanup()
        dummy_output.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
