import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from backend.engine.alignment_engine import AlignmentEngine
from backend.engine.field_alignment import analyze_field, field_crop
from backend.main import app
from backend.services.job_manager import JobManager
from test_astronomy import make_sky


def observed_motion(motion, index):
    sign = 1 if index % 2 else -1
    camera = np.vstack([cv2.getRotationMatrix2D((210, 160), sign * 0.08, 1), [0, 0, 1]])
    camera[:2, 2] += sign * np.array([2.5, -1.5])
    return (camera @ np.vstack([motion, [0, 0, 1]]))[:2]


def write_sequence(root, blank_index=None, dtype=np.uint8):
    image, stars = make_sky()
    paths, expected = [], []
    for index in range(12):
        # The pole is well outside the image; there is no star at that position.
        motion = cv2.getRotationMatrix2D((-280, -150), index * 0.3, 1.0)
        expected.append(motion)
        observed = observed_motion(motion, index)
        frame = cv2.warpAffine(image, observed, (420, 320))
        if index == blank_index:
            frame[:] = 0
        factor = 240 if dtype == np.uint16 else 1
        path = root / f"frame_{index:02}.png"
        cv2.imwrite(str(path), np.clip(frame * factor, 0, np.iinfo(dtype).max).astype(dtype))
        paths.append(path)
    return paths, np.array(expected), stars


class FieldAlignmentTests(unittest.TestCase):
    def test_corrects_shake_and_preserves_sky_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            paths, expected, stars = write_sequence(Path(folder))
            analysis = analyze_field(paths)
            self.assertTrue(all(frame.is_valid for frame in analysis.frames))
            errors = []
            for index, transform in enumerate(analysis.transforms):
                motion = observed_motion(expected[index], index)
                observed = np.vstack([motion, [0, 0, 1]])
                corrected = np.vstack([transform.matrix, [0, 0, 1]]) @ observed
                actual = stars @ corrected[:2, :2].T + corrected[:2, 2]
                target = stars @ expected[index, :, :2].T + expected[index, :, 2]
                errors.append(np.mean(np.linalg.norm(actual - target, axis=1)))
            self.assertLess(np.mean(errors), 0.75)
            # Full registration would give zero motion and collapse the trails.
            first = analysis.motion_at(analysis.times[0])
            last = analysis.motion_at(analysis.times[-1])
            displacement = last @ np.linalg.inv(first)
            self.assertGreater(abs(np.degrees(np.arctan2(displacement[1, 0], displacement[0, 0]))), 3)

    def test_cloud_frame_skipped_and_reacquired(self):
        with tempfile.TemporaryDirectory() as folder:
            paths, _, _ = write_sequence(Path(folder), blank_index=5)
            analysis = analyze_field(paths)
            self.assertEqual(analysis.skipped_frames, [5])
            self.assertTrue(analysis.frames[6].is_valid)
            for path in paths[:8]:
                cv2.imwrite(str(path), np.zeros((320, 420), np.uint8))
            with self.assertRaisesRegex(ValueError, "Not enough reliable star matches"):
                analyze_field(paths)

    def test_real_job_without_polaris_stacks_and_extends_16_bit_trails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_sequence(root, blank_index=5, dtype=np.uint16)
            manager = JobManager()
            job_id = manager.create_job({
                "input_dir": str(root), "output_file": str(root / "trails.tiff"),
                "extension_factor": 1.5, "ghost_frames_per_real": 2,
                "use_foreground_mask": False, "use_checkpoint": False,
            })
            updates = []
            manager.subscribe(job_id, updates.append)
            manager._run_job(job_id)
            job = manager.jobs[job_id]
            self.assertEqual(job["status"], "completed", job.get("error"))
            self.assertEqual(job["skipped_frames"], [5])
            output = cv2.imread(job["result_path"], cv2.IMREAD_UNCHANGED)
            self.assertEqual(output.dtype, np.uint16)
            self.assertGreater(output.max(), 10000)
            self.assertGreater(np.count_nonzero(output[:, :, 0] > 10000), 400)
            progress = [u["overall_progress"] for u in updates]
            self.assertEqual(progress, sorted(progress))
            self.assertEqual(progress[-1], 1)

    def test_auto_endpoint_returns_matching_stars_not_a_fake_polaris(self):
        with tempfile.TemporaryDirectory() as folder:
            write_sequence(Path(folder))
            client = TestClient(app)
            response = client.post("/api/stars/detect", json={"path": folder})
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertIsNone(data["polaris"])
            self.assertEqual(data["selection_mode"], "star_field")
            self.assertGreaterEqual(len(data["reference_stars"]), 6)
            self.assertTrue(all(0 <= x < 420 and 0 <= y < 320 for x, y in data["reference_stars"]))
            for step in (0, -1, None):
                response = client.post("/api/stars/detect", json={"path": folder, "frame_step": step})
                self.assertEqual(response.status_code, 422)

    def test_rotated_common_crop_has_no_invalid_pixels(self):
        from modules.transform import TransformData
        matrix = cv2.getRotationMatrix2D((210, 160), 2, 1)
        transform = TransformData(0, matrix[0, 2], matrix[1, 2], np.radians(-2), matrix, True)
        crop = field_crop([transform], 420, 320)
        mask = cv2.warpAffine(np.ones((320, 420), np.uint8), matrix, (420, 320))
        self.assertTrue(np.all(mask[crop.y_start:crop.y_end, crop.x_start:crop.x_end]))

    def test_pure_translation_extends_without_a_rotation_center(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image, _ = make_sky()
            for index in range(12):
                moved = cv2.warpAffine(image, np.float32([[1, 0, index * 0.8], [0, 1, -index * 0.5]]), (420, 320))
                cv2.imwrite(str(root / f"frame_{index:02}.png"), moved.astype(np.uint8))
            engine = AlignmentEngine(root, root / "trails.tiff", extension_factor=2,
                                     ghost_frames_per_real=1, use_checkpoint=False,
                                     use_foreground_mask=False, sort_by_time=False)
            engine.prepare()
            _, transforms = engine.run_pass1()
            self.assertFalse(engine.field_analysis.curved)
            crop = engine.calculate_crop(transforms)
            output = engine.run_pass2(transforms, crop)
            self.assertTrue(Path(output).exists())
            extended = cv2.imread(output)
            motion = engine.field_analysis.motion_at(22)
            np.testing.assert_allclose(motion[:2, 2], [17.6, -11], atol=0.3)
            engine.extension_factor = 1
            engine.run_pass2(transforms, crop)
            original = cv2.imread(output)
            self.assertGreater(np.count_nonzero(extended > 100),
                               1.15 * np.count_nonzero(original > 100))

    def test_checkpoint_resume_matches_uninterrupted_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_sequence(root)
            def interrupt(update):
                if update.get("stage") == "pass2" and update.get("current") == 11:
                    raise RuntimeError("simulated interruption")
            engine = AlignmentEngine(root, root / "trails.tiff", use_checkpoint=True,
                                     use_foreground_mask=False, progress_callback=interrupt)
            engine.prepare()
            _, transforms = engine.run_pass1()
            crop = engine.calculate_crop(transforms)
            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                engine.run_pass2(transforms, crop)
            self.assertTrue((root / "trails.field-checkpoint.npz").exists())
            resumed = AlignmentEngine(root, root / "trails.tiff", use_checkpoint=True,
                                      resume=True, use_foreground_mask=False)
            resumed.prepare()
            _, resumed_transforms = resumed.run_pass1()
            result = resumed.run_pass2(resumed_transforms, resumed.calculate_crop(resumed_transforms))
            recovered = cv2.imread(result)
            self.assertFalse((root / "trails.field-checkpoint.npz").exists())
            engine.resume = False
            engine.use_checkpoint = False
            engine.progress_callback = None
            engine.run_pass2(transforms, crop)
            np.testing.assert_array_equal(recovered, cv2.imread(result))

    def test_video_is_playable_and_has_even_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_sequence(root)
            engine = AlignmentEngine(root, root / "trails.tiff", video_enabled=True,
                                     use_checkpoint=False, use_foreground_mask=False)
            engine.prepare()
            _, transforms = engine.run_pass1()
            crop = engine.calculate_crop(transforms)
            engine.run_pass2(transforms, crop)
            video = cv2.VideoCapture(str(root / "trails.mp4"))
            try:
                self.assertTrue(video.isOpened())
                self.assertEqual(int(video.get(cv2.CAP_PROP_FRAME_COUNT)), 12)
                self.assertTrue(video.read()[0])
                self.assertEqual(crop.width % 2, 0)
                self.assertEqual(crop.height % 2, 0)
            finally:
                video.release()

    def test_video_slowdown_controls_encoded_frame_count(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_sequence(root)
            engine = AlignmentEngine(root, root / "trails.tiff", video_enabled=True,
                                     video_slowdown=2, use_checkpoint=False,
                                     use_foreground_mask=False)
            engine.prepare()
            _, transforms = engine.run_pass1()
            engine.run_pass2(transforms, engine.calculate_crop(transforms))
            video = cv2.VideoCapture(str(root / "trails.mp4"))
            try:
                self.assertTrue(video.isOpened())
                self.assertEqual(int(video.get(cv2.CAP_PROP_FRAME_COUNT)), 24)
            finally:
                video.release()


if __name__ == "__main__":
    unittest.main()
