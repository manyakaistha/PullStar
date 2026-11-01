"""Reject mixed-size source frames before expensive tracking and stacking."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from backend.engine.alignment_engine import AlignmentEngine
from core.validator import validate_image_consistency


class ImageConsistencyTests(unittest.TestCase):
    def make_sequence(self, folder):
        paths = []
        for index in range(12):
            path = Path(folder) / f'frame_{index:02}.png'
            self.assertTrue(cv2.imwrite(str(path), np.zeros((24, 32, 3), dtype=np.uint8)))
            paths.append(path)
        return paths

    def test_mismatch_after_tenth_frame_fails_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_sequence(folder)
            mismatch = Path(folder) / 'previous_stack.tiff'
            cv2.imwrite(str(mismatch), np.zeros((20, 28, 3), dtype=np.uint8))
            engine = AlignmentEngine(Path(folder), Path(folder) / 'new_stack.tiff')
            with self.assertRaises(ValueError) as failure:
                engine.prepare()
            self.assertIn('previous_stack.tiff (28x20)', str(failure.exception))
            self.assertIn('Expected 32x24', str(failure.exception))
            self.assertIn('Move cropped images', str(failure.exception))

    def test_current_output_is_excluded_and_matching_frames_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_sequence(folder)
            output = Path(folder) / 'previous_stack.tiff'
            cv2.imwrite(str(output), np.zeros((20, 28, 3), dtype=np.uint8))
            engine = AlignmentEngine(Path(folder), output)
            info = engine.prepare()
            self.assertEqual(info['num_images'], 12)
            self.assertNotIn(output, engine.image_paths)

    def test_undecodable_source_is_error(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = self.make_sequence(folder)
            paths[-1].write_bytes(b'not an image')
            errors, _ = validate_image_consistency(paths, check_timestamps=False)
            self.assertTrue(any('Cannot read source image frame_11.png' in error for error in errors))
