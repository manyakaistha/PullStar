#!/usr/bin/env python3
import sys
import argparse
from pathlib import Path

# Thin CLI wrapper around the new AlignmentEngine to satisfy the refactoring requirements.

def parse_arguments():
    parser = argparse.ArgumentParser(description="Star Trail Aligner")
    parser.add_argument("-i", "--input", required=True, help="Input directory")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("--extension", type=float, default=1.0, help="Trail extension factor")
    parser.add_argument(
        "--tail-taper",
        type=float,
        default=0.0,
        metavar="0..1",
        help="Fade strength toward the synthetic tail end (0 keeps it uniform)",
    )
    parser.add_argument(
        "--tail-angle-threshold",
        type=float,
        default=0.0,
        metavar="DEGREES",
        help="Stop synthetic tail growth after this angular offset; 0 disables the cutoff",
    )
    parser.add_argument("--auto", action="store_true", help="Match stars automatically; Polaris is not required")
    parser.add_argument("--no-raw-recovery", action="store_true", help="Disable sensor-domain star detection and RAW denoising")
    parser.add_argument("--raw-exposure", type=float, default=0, help="RAW exposure boost, 0 to 3 EV")
    parser.add_argument("--convert", choices=("none", "jpg", "tiff"), default="none",
                        help="Convert each frame once before alignment/stacking")
    parser.add_argument("--conversion-dir", help="Directory for converted frames; defaults to a temporary source-side folder")
    parser.add_argument("--save-frames", action="store_true", help="Export aligned real exposures")
    parser.add_argument("--no-stack", action="store_true", help="Skip trails; requires --save-frames")
    parser.add_argument("--image-format", choices=("tiff", "png", "jpg"), default="tiff")
    parser.add_argument("--video-format", choices=("auto", "mp4", "mov"), default="auto")
    parser.add_argument("--video", action="store_true", help="Generate a trail-lapse video")
    parser.add_argument("--video-fps", type=int, default=30, help="Video frame rate (default: 30)")
    parser.add_argument(
        "--image-resolution",
        choices=("source", "4k", "2k", "1080p", "720p"),
        default="source",
        help="Working/output image resolution; lower presets reduce stacking time",
    )
    parser.add_argument(
        "--video-resolution",
        choices=("source", "4k", "2k", "1080p", "720p"),
        default="source",
        help="Video long-edge resolution; does not upscale smaller stacks",
    )
    parser.add_argument(
        "--video-slowdown",
        type=int,
        choices=(1, 2, 4, 8),
        default=1,
        help="Slow-motion snapshots per exposure interval (default: 1; higher is slower)",
    )
    parser.add_argument(
        "--video-hyperlapse",
        action="store_true",
        help="Write one video frame per real exposure and skip synthetic states",
    )
    parser.add_argument(
        "--quality",
        choices=("high", "medium", "lossless", "prores", "hevc"),
        default="high",
        help="Video quality preset (default: high)",
    )
    parser.add_argument("--polaris-x", type=float, help="Polaris X coordinate")
    parser.add_argument("--polaris-y", type=float, help="Polaris Y coordinate")
    return parser.parse_args()

def main():
    args = parse_arguments()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path / ("aligned_images" if args.no_stack else "aligned_output.tiff")

    from backend.engine.alignment_engine import AlignmentEngine
    
    def progress_cb(data):
        if data.get('stage') == 'conversion' and 'current' in data:
            print(f"\rConverting: {data['current']}/{data['total']}", end="")
        elif data.get('stage') == 'pass1' and 'current' in data:
            print(f"\rTracking: {data['current']}/{data['total']}", end="")
        elif data.get('stage') == 'pass2' and 'current' in data:
            print(f"\r{'Exporting' if args.no_stack else 'Stacking'}: {data['current']}/{data['total']}", end="")

    engine = None
    try:
        engine = AlignmentEngine(
            input_dir=input_path,
            output_file=output_path,
            extension_factor=args.extension,
            tail_taper_strength=args.tail_taper,
            tail_angle_threshold=args.tail_angle_threshold,
            progress_callback=progress_cb,
            raw_noise_reduction=not args.no_raw_recovery,
            raw_exposure_ev=args.raw_exposure,
            conversion_format=args.convert,
            conversion_output_dir=Path(args.conversion_dir) if args.conversion_dir else None,
            video_enabled=args.video,
            video_fps=args.video_fps,
            video_slowdown=args.video_slowdown,
            image_resolution=args.image_resolution,
            video_resolution=args.video_resolution,
            video_hyperlapse=args.video_hyperlapse,
            quality=args.quality,
            save_frames=args.save_frames, no_stack=args.no_stack,
            image_format=args.image_format, video_format=args.video_format,
        )
        
        info = engine.prepare()
        print(f"\nPrepared {info['num_images']} images")
        
        polaris = None
        if (args.polaris_x is None) != (args.polaris_y is None):
            raise ValueError("Provide both --polaris-x and --polaris-y, or use --auto")
        if args.polaris_x is not None and args.polaris_y is not None:
            polaris = (args.polaris_x, args.polaris_y)
        elif args.auto:
            print("Matching the stellar field automatically (Polaris is not required).")
        else:
            print("Please provide --polaris-x and --polaris-y or use --auto")
            sys.exit(1)
            
        print("\nStarting Pass 1...")
        tracking_results, transforms = engine.run_pass1(polaris, None)
        
        print("\nCalculating crop...")
        crop = engine.calculate_crop(transforms)
        
        print("\nStarting Pass 2...")
        result = engine.run_pass2(transforms, crop, polaris)
        print(f"\nDone! Output saved to: {result}")
        
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

    finally:
        if engine is not None:
            engine.cleanup()

if __name__ == "__main__":
    main()
