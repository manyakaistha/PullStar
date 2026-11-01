"""Display previews must not replace the original high-bit-depth export."""
import os
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from fastapi import HTTPException
from backend.api.images_router import preview_image, download_image


class ImageDeliveryTests(unittest.TestCase):
    def test_tiff_preview_is_browser_readable_and_download_stays_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'stack.tiff'
            original = np.full((12, 16, 3), 32768, dtype=np.uint16)
            self.assertTrue(cv2.imwrite(str(path), original))
            original_bytes = path.read_bytes()
            response = preview_image(str(path))
            self.assertEqual(response.media_type, 'image/jpeg')
            decoded = cv2.imdecode(np.frombuffer(response.body, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(decoded.shape, original.shape)
            self.assertLessEqual(abs(int(decoded[0, 0, 0]) - 128), 1)
            download = download_image(str(path))
            self.assertEqual(download.filename, 'stack.tiff')
            self.assertIn('attachment', download.headers['content-disposition'])
            self.assertEqual(Path(download.path).read_bytes(), original_bytes)
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_delivery_rejects_non_images_and_missing_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'private.txt'
            path.write_text('not an image')
            for deliver in (preview_image, download_image):
                with self.assertRaises(HTTPException) as invalid:
                    deliver(str(path))
                self.assertEqual(invalid.exception.status_code, 403)
                with self.assertRaises(HTTPException) as missing:
                    deliver(os.path.join(folder, 'missing.tiff'))
                self.assertEqual(missing.exception.status_code, 404)
