"""Exercise real stacking progress, including an already-imported pipeline."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import backend.engine.pipeline  # Reproduce the cached tqdm import from the UI job.
from backend.services.job_manager import JobManager


class JobProgressTests(unittest.TestCase):
    def test_real_job_reports_stacking_and_monotonic_overall_progress(self):
        for extension in (1.0, 2.0):
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                for index in range(12):
                    image = np.zeros((64, 80, 3), dtype=np.uint8)
                    cv2.circle(image, (40, 30), 2, (255, 255, 255), -1)
                    cv2.imwrite(str(root / f'frame_{index:02}.png'), image)
                output = root / 'stack.tiff'
                manager = JobManager()
                job_id = manager.create_job({
                    'input_dir': str(root), 'output_file': str(output),
                    'polaris': (40, 30), 'extension_factor': extension,
                    'ghost_frames_per_real': 1, 'use_foreground_mask': False,
                    'use_checkpoint': False,
                })
                updates = []
                manager.subscribe(job_id, updates.append)
                manager._run_job(job_id)
                self.assertEqual(manager.jobs[job_id]['status'], 'completed')
                self.assertTrue(output.exists())
                stack_updates = [u for u in updates if u['stage'] == 'pass2']
                fractions = [u['progress'] for u in stack_updates]
                self.assertTrue(any(0 < p < 1 for p in fractions))
                self.assertEqual(fractions, sorted(fractions))
                self.assertEqual(fractions[-1], 1)
                self.assertEqual(stack_updates[-1]['total'], 13 if extension == 1 else 25)
                overall = [u['overall_progress'] for u in updates]
                self.assertEqual(overall, sorted(overall))
                self.assertTrue(all(u['overall_progress'] < 1 for u in updates[:-1]))
                self.assertEqual(overall[-1], 1)
                self.assertTrue(any(u['stage'] == 'crop_calc' for u in updates))
                self.assertEqual(updates[0]['overall_progress'], 0)
