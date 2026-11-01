"""Offline point-source detection and asterism matching, without a pole star.

Coordinates are image pixels (x, y), not catalogue identities or RA/Dec. A
rotation centre inferred from two exposures is not an identification of Polaris.
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import warnings

import cv2
import numpy as np
from astropy.stats import SigmaClip
from astropy.utils.exceptions import AstropyWarning
from photutils.detection import DAOStarFinder
from photutils.background import Background2D, MedianBackground
import astroalign
from core.cancellation import check_cancelled


MIN_MATCHES = 6
MAX_STARS = 100


@dataclass
class StarMatch:
    matrix: np.ndarray  # homogeneous transform: first frame -> second frame
    source: np.ndarray  # corresponding real star centroids, in the first frame
    target: np.ndarray
    confidence: float
    rms_error: float

    @property
    def rotation_angle(self) -> float:
        return float(np.degrees(np.arctan2(self.matrix[1, 0], self.matrix[0, 0])))

    @property
    def rotation_center(self) -> Optional[Tuple[float, float]]:
        # Translation and camera wobble can bias this estimate. Never use it as
        # the position of a star, or require that it lies inside the image.
        if abs(self.rotation_angle) < 0.05:
            return None
        rotation = self.matrix[:2, :2]
        rotation = rotation / np.sqrt(np.linalg.det(rotation))
        center = np.linalg.solve(np.eye(2) - rotation, self.matrix[:2, 2])
        return tuple(float(v) for v in center)


DETECTION_MAX_DIMENSION = 2048


def _prepare_detection_image(image: np.ndarray):
    """Stretch a bounded analysis copy and whiten its local background noise.

    Percentile white/black points exclude isolated saturated pixels. A linear
    stretch alone cannot improve signal-to-noise, so local sky subtraction,
    noise normalization, and a mild matched-scale smoothing follow it. No
    stretched pixels ever enter the export/stacking path.
    """
    original = np.asarray(image)
    if original.ndim not in (2, 3) or min(original.shape[:2]) < 12:
        return None
    if original.ndim == 3 and original.shape[2] not in (3, 4):
        return None
    height, width = original.shape[:2]
    scale = min(1.0, DETECTION_MAX_DIMENSION / max(height, width))
    if scale < 1:
        size = round(width * scale), round(height * scale)
        if original.ndim == 3:
            data = np.zeros((size[1], size[0]), dtype=np.float32)
            # Preserve sub-level flux during averaging. Resizing uint8 first
            # rounds away the faintest stars. Process one native channel at a
            # time to bound memory on 50-megapixel photographs.
            for channel, weight in enumerate((0.114, 0.587, 0.299)):
                data += cv2.resize(original[:, :, channel].astype(np.float32), size,
                                   interpolation=cv2.INTER_AREA) * weight
        else:
            data = cv2.resize(original.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    else:
        data = np.array(original, dtype=np.float32, copy=True)
        if data.ndim == 3:
            data = cv2.cvtColor(data[:, :, :3], cv2.COLOR_BGR2GRAY)
    finite = np.isfinite(data)
    if not finite.any():
        return None
    if not finite.all():
        data[~finite] = np.median(data[finite])
    contrast = float(np.ptp(data))
    if contrast <= 0:
        return None
    stride = max(1, int(np.sqrt(data.size / 160_000)))
    black, white = np.percentile(data[::stride, ::stride], [0.5, 99.5])
    data -= black
    data /= max(float(white - black), contrast * 1e-6)
    # Exclude extended bright structures, preserving small point sources. This
    # keeps walls/roof edges from consuming the controls in a nearly black sky.
    bright = np.uint8(data > np.percentile(data[::stride, ::stride], 98))
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(bright)
    extended = stats[:, cv2.CC_STAT_AREA] >= 256
    extended[0] = False
    foreground = cv2.dilate(np.uint8(extended[labels]), np.ones((9, 9), np.uint8)).astype(bool)
    residual = data - cv2.GaussianBlur(data, (0, 0), 10)
    box_size = max(16, min(64, min(data.shape) // 4))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        background = Background2D(
            residual, box_size, filter_size=3,
            sigma_clip=SigmaClip(sigma=3, maxiters=3),
            bkg_estimator=MedianBackground(), exclude_percentile=100, mask=foreground)
    noise_floor = max(float(np.percentile(background.background_rms_mesh, 10)) * 0.3, 1e-6)
    noise = np.maximum(background.background_rms, noise_floor)
    normalized = (residual - background.background) / noise
    smoothed = cv2.GaussianBlur(normalized, (0, 0), 0.7)
    return normalized, smoothed, foreground, np.array([width / data.shape[1], height / data.shape[0]])


def detect_sources(image: np.ndarray, max_stars: int = MAX_STARS,
                   cancel_check=None) -> np.ndarray:
    """Locate faint stars in an enhanced analysis copy, in original pixels.

    Multiscale DAOFIND candidates must pass an unsmoothed aperture signal/noise
    check, a hot-pixel check, and a compactness check. Spatial quotas keep bright
    foreground objects from taking all the matching control points.
    """
    check_cancelled(cancel_check)
    if max_stars <= 0:
        return np.empty((0, 2))
    prepared = _prepare_detection_image(image)
    check_cancelled(cancel_check)
    if prepared is None:
        return np.empty((0, 2))
    normalized, smoothed, foreground, pixel_scale = prepared
    height, width = normalized.shape
    yy, xx = np.mgrid[-4:5, -4:5]
    patch_y = np.arange(-4, 5)
    patch_x = np.arange(-4, 5)
    candidates = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        for fwhm in (2.5, 4.0, 6.0):
            check_cancelled(cancel_check)
            sources = DAOStarFinder(threshold=2.8, fwhm=fwhm,
                                    exclude_border=True)(smoothed, mask=foreground)
            if sources is None:
                continue
            xcol = "x_centroid" if "x_centroid" in sources.colnames else "xcentroid"
            ycol = "y_centroid" if "y_centroid" in sources.colnames else "ycentroid"
            # Bound work on heavily textured/noisy or very large frames, then
            # evaluate patches in batches to keep Python out of the hot path.
            order = np.argsort(np.asarray(sources["flux"]))[::-1][:5000]
            x_all = np.asarray(sources[xcol][order], dtype=float)
            y_all = np.asarray(sources[ycol][order], dtype=float)
            for start in range(0, len(order), 256):
                check_cancelled(cancel_check)
                x = x_all[start:start + 256]
                y = y_all[start:start + 256]
                finite = np.isfinite(x) & np.isfinite(y)
                xi = np.rint(np.where(finite, x, 0)).astype(np.intp)
                yi = np.rint(np.where(finite, y, 0)).astype(np.intp)
                finite &= (xi >= 5) & (yi >= 5) & (xi < width - 5) & (yi < height - 5)
                if not finite.any():
                    continue
                x, y, xi, yi = x[finite], y[finite], xi[finite], yi[finite]
                patches = normalized[yi[:, None, None] + patch_y[None, :, None],
                                     xi[:, None, None] + patch_x[None, None, :]]
                radius2 = ((xx[None] - (x - xi)[:, None, None]) ** 2 +
                           (yy[None] - (y - yi)[:, None, None]) ** 2)
                rim_values = np.where(radius2 > 12, patches, np.nan)
                signal = patches - np.nanmedian(rim_values, axis=(1, 2))[:, None, None]
                kernel = np.exp(-radius2 / (2 * (fwhm / 2.355) ** 2))
                snr = np.sum(signal * kernel, axis=(1, 2)) / np.sqrt(np.sum(kernel * kernel, axis=(1, 2)))
                positive = np.maximum(signal, 0)
                core = positive[:, 3:6, 3:6]
                core_sum = core.sum(axis=(1, 2))
                keep = ((snr >= 8) &
                        (core.max(axis=(1, 2)) <= 0.65 * np.maximum(core_sum, 1e-8)) &
                        (core_sum >= 0.25 * positive.sum(axis=(1, 2))))
                candidates.extend((float(px), float(py), float(score))
                                  for px, py, score in zip(x[keep], y[keep], snr[keep]))
    selected, occupied = [], {}
    quota = max(4, int(np.ceil(max_stars / 24)))
    for x, y, _ in sorted(candidates, key=lambda p: -p[2]):
        check_cancelled(cancel_check)
        cell = (int(x * 8 / width), int(y * 6 / height))
        if occupied.get(cell, 0) >= quota:
            continue
        if any((x - sx)**2 + (y - sy)**2 < 16 for sx, sy in selected):
            continue
        selected.append((x, y))
        occupied[cell] = occupied.get(cell, 0) + 1
        if len(selected) >= max_stars:
            break
    points = np.asarray(selected, dtype=float).reshape(-1, 2)
    # OpenCV resize maps pixel centres, including a half-pixel offset.
    return (points + 0.5) * pixel_scale - 0.5


def match_sources(source: np.ndarray, target: np.ndarray, cancel_check=None,
                  initial_translation=None) -> Optional[StarMatch]:
    """Match star triangles and validate the consensus across the whole field."""
    check_cancelled(cancel_check)
    if min(len(source), len(target)) < MIN_MATCHES:
        return None
    if initial_translation is not None:
        from scipy.spatial import cKDTree
        distances, indices = cKDTree(target).query(source + initial_translation)
        # A target centroid may correspond to only one source centroid.
        used, pairs = set(), []
        for index in np.argsort(distances):
            if distances[index] < 4 and int(indices[index]) not in used:
                pairs.append(index)
                used.add(int(indices[index]))
        if len(pairs) >= MIN_MATCHES:
            src, dst = source[pairs], target[indices[pairs]]
            matrix, inliers = cv2.estimateAffinePartial2D(
                src, dst, method=cv2.RANSAC, ransacReprojThreshold=2, maxIters=2000)
            if matrix is not None and 0.98 <= np.sqrt(np.linalg.det(matrix[:, :2])) <= 1.02:
                keep = inliers.ravel().astype(bool)
                result = _validate_correspondences(source, target, src[keep], dst[keep])
                if result is not None:
                    check_cancelled(cancel_check)
                    return result
    # Faint RAW noise and foreground texture can fill the tail of the source
    # list. If that pool cannot establish a reliable field, retry the strongest
    # candidates. Keep every quality gate and the original pool denominator:
    # a smaller trial must not turn a handful of coincidences into confidence.
    largest_pool = max(len(source), len(target))
    for controls in dict.fromkeys(min(largest_pool, budget) for budget in (MAX_STARS, 60, 40)):
        check_cancelled(cancel_check)
        result = _match_source_pool(source, target, controls, cancel_check)
        if result is not None:
            return result
    return None


def _match_source_pool(source, target, controls, cancel_check):
    try:
        transform, (src, dst) = astroalign.find_transform(
            source, target, max_control_points=controls)
    except (ValueError, astroalign.MaxIterError):
        check_cancelled(cancel_check)
        return None
    check_cancelled(cancel_check)
    matrix = np.asarray(transform.params, dtype=float)
    if not np.isfinite(matrix).all() or not 0.98 <= transform.scale <= 1.02:
        return None
    return _validate_correspondences(source, target, np.asarray(src), np.asarray(dst))


def _validate_correspondences(source, target, src, dst):
    # Refine using a rigid (unit-scale) least-squares fit. Exposure/PSF changes
    # must not make the rendered sky grow or shrink.
    if len(src) < MIN_MATCHES:
        return None
    for _ in range(2):
        a, b = src.mean(axis=0), dst.mean(axis=0)
        u, _, vt = np.linalg.svd((src - a).T @ (dst - b))
        rotation = vt.T @ u.T
        if np.linalg.det(rotation) <= 0:
            return None
        matrix = np.eye(3)
        matrix[:2, :2] = rotation
        matrix[:2, 2] = b - rotation @ a
        errors = np.linalg.norm(src @ rotation.T + matrix[:2, 2] - dst, axis=1)
        keep = errors <= 2.0
        src, dst = src[keep], dst[keep]
        if len(src) < MIN_MATCHES:
            return None
    rms = float(np.sqrt(np.mean(np.square(errors[keep]))))
    fraction = len(src) / min(len(source), len(target))
    # Dim fields can have a large candidate pool but only a subset of stars
    # shared between exposures. Twenty precise correspondences are already a
    # strong consensus; retain the original fraction requirement for small pools.
    required = max(MIN_MATCHES, min(20, int(np.ceil(0.3 * min(len(source), len(target))))))
    if len(src) < required or rms > 1.5 or np.linalg.norm(np.ptp(src, axis=0)) < 20:
        return None
    return StarMatch(matrix, src, dst, float(min(1, fraction) / (1 + rms)), rms)


def match_images(first: np.ndarray, second: np.ndarray, cancel_check=None) -> Optional[StarMatch]:
    if first.shape[:2] != second.shape[:2]:
        return None
    return match_sources(detect_sources(first, cancel_check=cancel_check),
                         detect_sources(second, cancel_check=cancel_check), cancel_check=cancel_check)
