"""Compare detection and render representative, consistent real JPEG sequences.

Example:
    uv run python scripts/validate_dim_detection.py --data-dir ../naman-test-data \
        --baseline-ref 162b8cf --render --output-dir /tmp/dim-star-validation

Only reads source photographs. Reports, symlinks, and renders go to output-dir.
A folder can contain multiple sessions or sizes; test its longest consistent
JPEG burst and report the other groups rather than mixing them into one job.
"""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from PIL import Image
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.engine.alignment_engine import AlignmentEngine
from modules import astronomy
from modules.io_utils import load_image


def jpeg_bursts(folder):
    groups, current, previous = [], [], None
    for path in sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg')):
        with Image.open(path) as image:
            shape = image.size
        match = re.search(r'(20\d{6})_(\d{6})', path.stem)
        timestamp = datetime.strptime(''.join(match.groups()), '%Y%m%d%H%M%S') if match else None
        if previous is not None:
            old_shape, old_time = previous
            if shape != old_shape or (timestamp and old_time and (timestamp-old_time).total_seconds() > 1800):
                groups.append(current)
                current = []
        current.append(path)
        previous = shape, timestamp
    if current:
        groups.append(current)
    return sorted(groups, key=len, reverse=True)


def baseline_module(ref, output):
    source = subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{ref}:modules/astronomy.py'])
    path = output / 'baseline_astronomy.py'
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location('_dim_validation_baseline', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def measure_baseline(paths, module, label):
    frames, reference, previous = [], None, None
    for index, path in enumerate(paths):
        points = module.detect_sources(load_image(path))
        match, valid = None, False
        if reference is None and len(points) >= module.MIN_MATCHES:
            reference = previous = points
            valid = True
        elif reference is not None:
            match = module.match_sources(reference, points)
            if match is None and previous is not reference:
                match = module.match_sources(previous, points)
            valid = match is not None
            if valid:
                previous = points
        frames.append({'file': path.name, 'detected': len(points), 'valid': valid,
                       'matches': len(match.source) if match else (len(points) if index == 0 else 0)})
        print(json.dumps({'series': label, 'phase': 'baseline', 'frame': index+1, 'valid': valid}), flush=True)
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--baseline-ref')
    parser.add_argument('--baseline-report', type=Path, help='Reuse an unchanged-source baseline from a previous run')
    parser.add_argument('--samples', type=int, default=12)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    if args.samples < 10:
        parser.error('--samples must be at least 10')
    output = args.output_dir or Path(tempfile.mkdtemp(prefix='dim-star-validation-'))
    if output.resolve().is_relative_to(args.data_dir.resolve()):
        parser.error('--output-dir must be outside --data-dir to keep the source collection unchanged')
    output.mkdir(parents=True, exist_ok=True)
    if args.baseline_ref and args.baseline_report:
        parser.error('Choose --baseline-ref or --baseline-report')
    previous = json.loads(args.baseline_report.read_text()) if args.baseline_report else None
    baseline = baseline_module(args.baseline_ref, output) if args.baseline_ref else None
    report = {'baseline_ref': previous['baseline_ref'] if previous else args.baseline_ref,
              'samples_per_series': args.samples, 'series': [], 'raw_probes': []}
    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2))
    for folder in sorted(p for p in args.data_dir.iterdir() if p.is_dir()):
        groups = jpeg_bursts(folder)
        if not groups or len(groups[0]) < 10:
            continue
        paths = groups[0][:args.samples]
        label = folder.name
        row = {'dataset': label, 'available_group_lengths': [len(g) for g in groups],
               'files': [p.name for p in paths]}
        report['series'].append(row)
        if previous:
            old = next((entry for entry in previous['series'] if entry['dataset'] == label), None)
            if old is None or old['files'] != row['files']:
                raise SystemExit('Baseline report does not describe the same source sequence')
            row['baseline'] = old['baseline']
        if baseline is not None:
            row['baseline'] = measure_baseline(paths, baseline, label)
        target = output / label
        inputs = target / 'inputs'
        inputs.mkdir(parents=True, exist_ok=True)
        for path in paths:
            link = inputs / path.name
            if not link.exists():
                link.symlink_to(path.resolve())
        def progress(event):
            if event.get('current') is not None and event.get('stage') in ('pass1', 'pass2'):
                print(json.dumps({'series': label, 'phase': event['stage'], 'frame': event['current'],
                                  'total': event['total']}), flush=True)
        engine = AlignmentEngine(inputs, target / 'trails.tiff', sort_by_time=False,
                                 use_checkpoint=False, progress_callback=progress)
        start = time.perf_counter()
        try:
            engine.prepare()
            frames, transforms = engine.run_pass1()
            row['enhanced'] = [{'file': paths[f.frame_index].name, 'valid': f.is_valid,
                                'matches': f.num_matches} for f in frames]
            row['analysis_seconds'] = round(time.perf_counter()-start, 3)
            if args.render:
                crop = engine.calculate_crop(transforms)
                rendered = engine.run_pass2(transforms, crop)
                result = cv2.imread(rendered, cv2.IMREAD_UNCHANGED)
                if result is None or not np.isfinite(result).all() or result.max() == 0:
                    raise RuntimeError('Rendered image is missing or empty')
                row['output'] = {'path': rendered, 'shape': list(result.shape), 'dtype': str(result.dtype)}
                scale = min(1, 1200/result.shape[1])
                cv2.imwrite(str(target/'preview.jpg'), cv2.resize(result, None, fx=scale, fy=scale))
            row['seconds'] = round(time.perf_counter()-start, 3)
            row['status'] = 'passed'
        except Exception as exc:
            row['status'], row['error'] = 'failed', f'{type(exc).__name__}: {exc}'
        save()
        print(json.dumps({'series': label, 'status': row['status'], 'seconds': row.get('seconds'),
                          'valid_frames': sum(f['valid'] for f in row.get('enhanced', []))}), flush=True)
        # Probe decoder support separately; this is not a claim of RAW alignment.
        raw_paths = sorted(folder.glob('*.dng'))
        if raw_paths:
            probe = {'dataset': label, 'file': raw_paths[0].name}
            try:
                raw = load_image(raw_paths[0])
                probe.update(status='decoded', dtype=str(raw.dtype), shape=list(raw.shape))
            except Exception as exc:
                probe.update(status='decoder_error', error=f'{type(exc).__name__}: {exc}')
            report['raw_probes'].append(probe)
            save()
    if not report['series']:
        raise SystemExit('No consistent JPEG burst with ten frames was found')
    print('REPORT:', output/'report.json', flush=True)
    if any(row['status'] != 'passed' for row in report['series']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
