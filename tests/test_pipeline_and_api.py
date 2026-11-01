import unittest
from unittest.mock import patch, MagicMock
import os
import shutil
import tempfile
import numpy as np
import cv2
from pathlib import Path
from datetime import datetime, timedelta


# Project Imports
from modules.io_utils import get_image_list
from backend.api.images_router import router as images_router
from backend.api.router import stars_router
from modules.transform import calculate_common_crop, TransformData, CropRegion
from backend.engine.alignment_engine import AlignmentEngine

# Setup FastAPI test client
from fastapi import FastAPI

class TestPipelineAndAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        # Keep this suite independent of a developer's private photo library.
        from tests.test_field_alignment import write_sequence
        cls.detect_dir = Path(cls.test_dir) / "detect_stars"
        cls.detect_dir.mkdir()
        write_sequence(cls.detect_dir)
        cls.engine_dir = Path(cls.test_dir) / "engine_test"
        cls.engine_dir.mkdir()
        for frame in sorted(cls.detect_dir.glob("*.png"))[:3]:
            shutil.copy2(frame, cls.engine_dir / frame.name)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir)

    def test_get_image_list_sorting(self):
        d = Path(self.test_dir) / "sorting"
        d.mkdir(exist_ok=True)
        # Create files out of order in naming
        (d / "image_C.jpg").touch()
        (d / "image_A.jpg").touch()
        (d / "image_B.jpg").touch()

        def mock_exif(path):
            name = path.name
            # Reverse order of time compared to name
            if "A" in name: return datetime(2023, 1, 3)
            if "B" in name: return datetime(2023, 1, 2)
            if "C" in name: return datetime(2023, 1, 1)
            return None

        with patch("modules.io_utils.get_exif_datetime", side_effect=mock_exif):
            # Sort by time
            files_time = get_image_list(d, sort_by_time=True)
            self.assertEqual([f.name for f in files_time], ["image_C.jpg", "image_B.jpg", "image_A.jpg"])

            # Sort by filename
            files_name = get_image_list(d, sort_by_time=False)
            self.assertEqual([f.name for f in files_name], ["image_A.jpg", "image_B.jpg", "image_C.jpg"])

    def test_get_metadata_gap_detection(self):
        d = Path(self.test_dir) / "metadata"
        d.mkdir(exist_ok=True)

        files = [Path(d / f"img_{i}.jpg") for i in range(4)]
        for f in files: f.touch()

        def mock_list(*args, **kwargs):
            return files

        def mock_info(*args, **kwargs):
            return {"width": 100, "height": 100}

        def mock_exif(path):
            name = path.name
            times = {
                "img_0.jpg": datetime(2023, 1, 1, 12, 0, 0),
                "img_1.jpg": datetime(2023, 1, 1, 12, 0, 10),
                "img_2.jpg": datetime(2023, 1, 1, 12, 0, 40), # 30s gap
                "img_3.jpg": datetime(2023, 1, 1, 12, 0, 50),
            }
            return times[name]

        with patch("modules.io_utils.get_image_list", side_effect=mock_list), \
             patch("modules.io_utils.get_image_info", side_effect=mock_info), \
             patch("modules.io_utils.get_exif_datetime", side_effect=mock_exif):

            from backend.api.images_router import DirectoryRequest, get_metadata
            req = DirectoryRequest(path=str(d))
            resp = get_metadata(req)
            data = resp["metadata"]

            self.assertEqual(len(data), 4)
            self.assertFalse(data[0]["gap_detected"])
            self.assertFalse(data[1]["gap_detected"])
            self.assertTrue(data[2]["gap_detected"])
            self.assertFalse(data[3]["gap_detected"])

    def test_detect_stars_endpoint(self):
        from backend.api.router import DetectRequest, detect_stars
        req = DetectRequest(path=str(self.detect_dir), frame_step=1)
        data = detect_stars(req)

        self.assertIn("polaris", data)
        self.assertIn("confidence", data)
        # A fitted rotation centre is not an identification of Polaris.
        self.assertIsNone(data["polaris"])
        self.assertGreaterEqual(len(data["reference_stars"]), 6)
        self.assertEqual(data["selection_mode"], "star_field")

    def test_calculate_common_crop(self):
        matrix = np.eye(2, 3)
        t1 = TransformData(frame_index=0, dx=0.0, dy=0.0, rotation=0.0, matrix=matrix, is_valid=True)
        t2 = TransformData(frame_index=1, dx=10.0, dy=-5.0, rotation=0.0, matrix=matrix, is_valid=True)
        t3 = TransformData(frame_index=2, dx=-5.0, dy=20.0, rotation=0.0, matrix=matrix, is_valid=True)

        crop = calculate_common_crop([t1, t2, t3], 100, 100)

        self.assertEqual(crop.x_start, 10)
        self.assertEqual(crop.x_end, 95)
        self.assertEqual(crop.y_start, 20)
        self.assertEqual(crop.y_end, 95)
        self.assertEqual(crop.width, 85)
        self.assertEqual(crop.height, 75)

    @patch("backend.engine.alignment_engine.validate_inputs", return_value=([], []))
    def test_alignment_engine_dry_run(self, mock_validate):
        output_file = Path(self.engine_dir) / "output.tiff"
        engine = AlignmentEngine(
            input_dir=self.engine_dir,
            output_file=output_file,
            video_enabled=False,
            use_checkpoint=False
        )

        info = engine.prepare()
        self.assertEqual(info["num_images"], 3)

        # Run pass 1
        polaris = (1500.0, 1000.0)
        results, transforms = engine.run_pass1(polaris=polaris)

        self.assertEqual(len(results), 3)
        self.assertEqual(len(transforms), 3)

        for t in transforms:
            self.assertTrue(hasattr(t, 'dx'))
            self.assertTrue(hasattr(t, 'dy'))

        crop = calculate_common_crop(
            transforms,
            info["first_info"]["width"],
            info["first_info"]["height"]
        )

        # Run pass 2
        engine.run_pass2(transforms, crop, polaris=polaris)

        self.assertTrue(output_file.exists())

        # Verify stacked output is a valid image
        stacked = cv2.imread(str(output_file), cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(stacked)

        # Check dimensions
        self.assertEqual(stacked.shape[0], crop.height)
        self.assertEqual(stacked.shape[1], crop.width)

if __name__ == "__main__":
    unittest.main()
