from pathlib import Path

import cv2
import numpy as np

from backend.engine.alignment_engine import AlignmentEngine


def write_frames(folder: Path, count: int = 10) -> None:
    for index in range(count):
        image = np.zeros((32, 40, 3), dtype=np.uint8)
        cv2.circle(image, (20, 16), 2, (255, 255, 255), -1)
        assert cv2.imwrite(str(folder / f"frame_{index:02}.png"), image)


def test_jpeg_conversion_uses_source_side_temp_and_cleans_up(tmp_path):
    write_frames(tmp_path)
    engine = AlignmentEngine(tmp_path, tmp_path / "stack.tiff", conversion_format="jpg",
                             sort_by_time=False, use_checkpoint=False)
    info = engine.prepare()
    converted_dir = engine.image_paths[0].parent
    assert info["num_images"] == 10
    assert converted_dir.name.startswith(".staraligner-converted-")
    assert cv2.imread(str(engine.image_paths[0]), cv2.IMREAD_UNCHANGED).dtype == np.uint8
    engine.cleanup()
    assert not converted_dir.exists()


def test_tiff_conversion_can_be_kept_in_selected_folder(tmp_path):
    source = tmp_path / "source"
    selected = tmp_path / "converted"
    source.mkdir()
    write_frames(source)
    engine = AlignmentEngine(source, source / "stack.tiff", conversion_format="tiff",
                             conversion_output_dir=selected, sort_by_time=False,
                             use_checkpoint=False)
    info = engine.prepare()
    assert Path(info["converted_files_dir"]) == selected.resolve()
    assert cv2.imread(str(engine.image_paths[0]), cv2.IMREAD_UNCHANGED).dtype == np.uint16
    engine.cleanup()
    assert len(list(selected.glob("*.tiff"))) == 10
