"""
Star Trail Aligner - Input Validator

Pre-flight validation checks to ensure inputs are valid before processing.
Provides clear error messages for common issues.
"""

import os
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Union
from datetime import datetime
from core.cancellation import check_cancelled
from core.parallel import ordered_map


def validate_inputs(
    image_list: List[Path],
    ref_polaris_xy: Optional[Tuple[float, float]] = None,
    ref_star2_xy: Optional[Tuple[float, float]] = None,
    extension_factor: float = 1.0,
    output_path: Optional[Path] = None,
    min_images: int = 10,
    cancel_check=None,
) -> Tuple[List[str], List[str]]:
    """
    Validate all inputs before processing.
    
    Args:
        image_list: List of paths to image files
        ref_polaris_xy: Reference Polaris coordinates (optional for pre-GUI check)
        ref_star2_xy: Reference second star coordinates (optional)
        extension_factor: Trail extension multiplier (1.0 = no extension)
        output_path: Intended output path (optional)
        min_images: Minimum number of images required
        
    Returns:
        Tuple of (errors, warnings) - Lists of error and warning messages
        Empty errors list means validation passed
    """
    errors = []
    warnings = []
    
    # ==========================================================================
    # Check 1: Minimum image count
    # ==========================================================================
    if len(image_list) < min_images:
        errors.append(
            f"Need at least {min_images} images for meaningful trail alignment, "
            f"found {len(image_list)}"
        )
    
    # ==========================================================================
    # Check 2: All files exist and are readable
    # ==========================================================================
    missing_files = []
    unreadable_files = []
    
    for img_path in image_list:
        check_cancelled(cancel_check)
        path = Path(img_path)
        if not path.exists():
            missing_files.append(str(path))
        elif not os.access(path, os.R_OK):
            unreadable_files.append(str(path))
    
    if missing_files:
        if len(missing_files) <= 5:
            errors.append(f"Images not found: {', '.join(missing_files)}")
        else:
            errors.append(f"{len(missing_files)} images not found. First few: {', '.join(missing_files[:3])}")
    
    if unreadable_files:
        errors.append(f"Cannot read {len(unreadable_files)} image(s) - check permissions")
    
    # ==========================================================================
    # Check 3: Polaris coordinates validity (if provided)
    # ==========================================================================
    if ref_polaris_xy is not None:
        px, py = ref_polaris_xy
        if px < 0 or py < 0:
            errors.append(f"Polaris coordinates must be positive, got ({px}, {py})")
    
    # ==========================================================================
    # Check 4: Extension factor validity
    # ==========================================================================
    if extension_factor < 1.0:
        errors.append(f"Extension factor must be >= 1.0, got {extension_factor}")
    elif extension_factor > 10.0:
        warnings.append(
            f"Extension factor {extension_factor}x is very high. "
            "Results may look unrealistic."
        )
    
    # ==========================================================================
    # Check 5: Extension without rotation warning
    # ==========================================================================
    if extension_factor > 1.05 and ref_star2_xy is None:
        warnings.append(
            f"Extension factor {extension_factor}x works best with two-star rotation. "
            "Consider selecting a second reference star for better results."
        )
    
    # ==========================================================================
    # Check 6: Disk space check
    # ==========================================================================
    try:
        # Calculate approximate space needed
        existing_files = [Path(p) for p in image_list if Path(p).exists()]
        if existing_files:
            total_input_size = sum(f.stat().st_size for f in existing_files)
            
            # Estimate output size (roughly 5x input for processing + output)
            estimated_space_needed = total_input_size * 5
            
            # Check disk space at output location or current directory
            check_path = output_path.parent if output_path else Path('.')
            disk_usage = shutil.disk_usage(check_path)
            free_space = disk_usage.free
            
            if free_space < estimated_space_needed:
                errors.append(
                    f"Insufficient disk space. "
                    f"Need approximately {estimated_space_needed / (1024**3):.1f} GB, "
                    f"but only {free_space / (1024**3):.1f} GB available."
                )
            elif free_space < estimated_space_needed * 1.5:
                warnings.append(
                    f"Disk space is limited. "
                    f"~{estimated_space_needed / (1024**3):.1f} GB needed, "
                    f"{free_space / (1024**3):.1f} GB available."
                )
    except Exception as e:
        # Don't fail validation if disk check fails
        warnings.append(f"Could not verify disk space: {e}")
    
    # ==========================================================================
    # Check 7: Output path writability
    # ==========================================================================
    if output_path:
        output_dir = Path(output_path).parent
        if output_dir.exists() and not os.access(output_dir, os.W_OK):
            errors.append(f"Cannot write to output directory: {output_dir}")
    
    # ==========================================================================
    # Check 8: macOS Rosetta 2 detection (running x86 on Apple Silicon)
    # ==========================================================================
    try:
        import platform
        import subprocess as sp
        if platform.system() == 'Darwin' and platform.machine() == 'x86_64':
            # Check if this is actually Apple Silicon running Rosetta
            result = sp.run(
                ['sysctl', '-n', 'sysctl.proc_translated'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() == '1':
                warnings.append(
                    "Running under Rosetta 2 (x86 emulation on Apple Silicon). "
                    "Performance may be reduced. Consider running natively."
                )
    except Exception:
        pass  # Non-critical check
    
    # ==========================================================================
    # Check 9: macOS thermal throttling detection
    # ==========================================================================
    try:
        import platform
        if platform.system() == 'Darwin':
            import subprocess as sp
            result = sp.run(
                ['pmset', '-g', 'therm'],
                capture_output=True, text=True, timeout=5
            )
            if 'CPU_Speed_Limit' in result.stdout:
                for line in result.stdout.splitlines():
                    if 'CPU_Speed_Limit' in line:
                        try:
                            limit = int(line.split('=')[-1].strip())
                            if limit < 100:
                                warnings.append(
                                    f"CPU thermal throttling detected ({limit}% speed). "
                                    "Processing may be slower than expected."
                                )
                        except ValueError:
                            pass
    except Exception:
        pass  # Non-critical check
    
    return errors, warnings


def validate_image_consistency(
    image_list: List[Path],
    check_dimensions: bool = True,
    check_timestamps: bool = True,
    cancel_check=None,
) -> Tuple[List[str], List[str]]:
    """
    Validate that images in the list are consistent with each other.
    
    Args:
        image_list: List of paths to image files
        check_dimensions: Whether to verify all images have same dimensions
        check_timestamps: Whether to check EXIF timestamp ordering
        
    Returns:
        Tuple of (errors, warnings)
    """
    from modules.io_utils import get_image_info
    
    errors = []
    warnings = []
    
    if len(image_list) < 2:
        return errors, warnings
    
    # ==========================================================================
    # Check image dimensions consistency
    # ==========================================================================
    if check_dimensions:
        reference = None
        inconsistent = []
        def read_info(img_path):
            try:
                info = get_image_info(img_path)
                return img_path, info, None
            except Exception as error:
                return img_path, None, error

        workers = 4 if len(image_list) >= 16 else 1
        for img_path, info, error in ordered_map(read_info, image_list,
                                                 workers=workers,
                                                 cancel_check=cancel_check):
            check_cancelled(cancel_check)
            if error is not None:
                errors.append(f"Cannot read source image {Path(img_path).name}: {error}")
                continue
            dimensions = (info['width'], info['height'])
            if reference is None:
                reference = dimensions
            elif dimensions != reference:
                inconsistent.append(f"{Path(img_path).name} ({dimensions[0]}x{dimensions[1]})")
        if inconsistent:
            errors.append(
                f"Image dimensions inconsistent. Expected {reference[0]}x{reference[1]}, "
                f"but found: {', '.join(inconsistent[:3])}. "
                "All source frames must have the same dimensions. "
                "Move cropped images and previous alignment outputs out of the source folder."
            )
    
    # ==========================================================================
    # Check timestamp ordering (non-monotonic detection)
    # ==========================================================================
    if check_timestamps:
        try:
            from modules.io_utils import get_timestamps_for_files
            timestamps = get_timestamps_for_files(image_list[:20], cancel_check=cancel_check)  # Check first 20
            
            if len(timestamps) >= 2:
                non_monotonic = 0
                for i in range(len(timestamps) - 1):
                    if timestamps[i + 1] < timestamps[i]:
                        non_monotonic += 1
                
                if non_monotonic > 0:
                    warnings.append(
                        f"Found {non_monotonic} non-monotonic timestamp(s) in the first "
                        f"{min(20, len(image_list))} images. Images may be out of order. "
                        "Consider using --sort-by-name if filenames reflect capture order."
                    )
        except Exception:
            pass  # Timestamp extraction is optional
    
    check_cancelled(cancel_check)
    return errors, warnings


def format_validation_results(errors: List[str], warnings: List[str]) -> str:
    """
    Format validation results for display.
    
    Args:
        errors: List of error messages
        warnings: List of warning messages
        
    Returns:
        Formatted string for display
    """
    lines = []
    
    if errors:
        lines.append("❌ VALIDATION ERRORS:")
        for i, error in enumerate(errors, 1):
            lines.append(f"   {i}. {error}")
    
    if warnings:
        if errors:
            lines.append("")
        lines.append("⚠️  WARNINGS:")
        for i, warning in enumerate(warnings, 1):
            lines.append(f"   {i}. {warning}")
    
    if not errors and not warnings:
        lines.append("✓ All validation checks passed")
    
    return "\n".join(lines)
