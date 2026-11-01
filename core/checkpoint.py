"""
Star Trail Aligner - Checkpoint System

Provides fault-tolerant processing through checkpoint/resume functionality.
Saves progress periodically so processing can resume after interruption.
"""

import pickle
import glob
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np


def save_checkpoint(
    alignment_data: List[Dict[str, Any]],
    pass_num: int,
    frame_num: int,
    checkpoint_dir: Path,
    additional_data: Optional[Dict[str, Any]] = None
) -> Path:
    """
    Save current progress to checkpoint file.
    
    Args:
        alignment_data: List of alignment dictionaries (one per processed frame)
        pass_num: Current pass number (1 or 2)
        frame_num: Last successfully processed frame index
        checkpoint_dir: Directory to save checkpoint files
        additional_data: Optional additional data to save (e.g., crop region)
        
    Returns:
        Path to the saved checkpoint file
    """
    checkpoint_dir = Path(checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    # Create checkpoint filename with timestamp for uniqueness
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint_path = checkpoint_dir / f'checkpoint_pass{pass_num}_frame{frame_num:04d}_{timestamp}.pkl'
    
    # Prepare checkpoint data
    checkpoint_data = {
        'alignment_data': alignment_data,
        'last_frame': frame_num,
        'pass_num': pass_num,
        'timestamp': datetime.now().isoformat(),
        'version': '2.0'  # For compatibility checking
    }
    
    if additional_data:
        checkpoint_data['additional'] = additional_data
    
    # Save checkpoint
    with open(checkpoint_path, 'wb') as f:
        pickle.dump(checkpoint_data, f, protocol=pickle.HIGHEST_PROTOCOL)
    
    # Clean up old checkpoints for this pass (keep only last 3)
    _cleanup_old_checkpoints(checkpoint_dir, pass_num, keep=3)
    
    return checkpoint_path


def load_checkpoint(
    checkpoint_dir: Path,
    pass_num: int
) -> Tuple[Optional[List[Dict[str, Any]]], int, Optional[Dict[str, Any]]]:
    """
    Load most recent checkpoint if available.
    
    Args:
        checkpoint_dir: Directory containing checkpoint files
        pass_num: Pass number to load checkpoint for
        
    Returns:
        Tuple of (alignment_data, last_frame_index, additional_data)
        Returns (None, 0, None) if no checkpoint found
    """
    checkpoint_dir = Path(checkpoint_dir)
    
    if not checkpoint_dir.exists():
        return None, 0, None
    
    # Find all checkpoints for this pass
    pattern = f'checkpoint_pass{pass_num}_*.pkl'
    checkpoints = sorted(checkpoint_dir.glob(pattern))
    
    if not checkpoints:
        return None, 0, None
    
    # Load the most recent checkpoint
    latest = checkpoints[-1]
    
    try:
        with open(latest, 'rb') as f:
            data = pickle.load(f)
        
        # Version check
        version = data.get('version', '1.0')
        if version != '2.0':
            print(f"Warning: Checkpoint version {version} may not be fully compatible")
        
        alignment_data = data.get('alignment_data', [])
        last_frame = data.get('last_frame', 0)
        additional_data = data.get('additional', None)
        
        print(f"Loaded checkpoint: {latest.name}")
        print(f"  Last completed frame: {last_frame}")
        print(f"  Checkpoint timestamp: {data.get('timestamp', 'unknown')}")
        
        return alignment_data, last_frame, additional_data
        
    except Exception as e:
        print(f"Warning: Failed to load checkpoint {latest}: {e}")
        return None, 0, None


def _cleanup_old_checkpoints(checkpoint_dir: Path, pass_num: int, keep: int = 3):
    """
    Remove old checkpoint files, keeping only the most recent ones.
    
    Args:
        checkpoint_dir: Directory containing checkpoint files
        pass_num: Pass number to clean checkpoints for
        keep: Number of checkpoints to keep
    """
    pattern = f'checkpoint_pass{pass_num}_*.pkl'
    checkpoints = sorted(checkpoint_dir.glob(pattern))
    
    # Remove all but the most recent 'keep' checkpoints
    for old_checkpoint in checkpoints[:-keep]:
        try:
            old_checkpoint.unlink()
        except Exception:
            pass  # Ignore deletion errors


def checkpoint_exists(checkpoint_dir: Path, pass_num: int) -> bool:
    """
    Check if any checkpoint exists for the given pass.
    
    Args:
        checkpoint_dir: Directory containing checkpoint files
        pass_num: Pass number to check
        
    Returns:
        True if at least one checkpoint exists
    """
    checkpoint_dir = Path(checkpoint_dir)
    
    if not checkpoint_dir.exists():
        return False
    
    pattern = f'checkpoint_pass{pass_num}_*.pkl'
    checkpoints = list(checkpoint_dir.glob(pattern))
    
    return len(checkpoints) > 0


def clear_checkpoints(checkpoint_dir: Path, pass_num: Optional[int] = None):
    """
    Clear all checkpoints (optionally for a specific pass).
    
    Args:
        checkpoint_dir: Directory containing checkpoint files
        pass_num: If specified, only clear checkpoints for this pass
    """
    checkpoint_dir = Path(checkpoint_dir)
    
    if not checkpoint_dir.exists():
        return
    
    if pass_num is not None:
        pattern = f'checkpoint_pass{pass_num}_*.pkl'
    else:
        pattern = 'checkpoint_*.pkl'
    
    for checkpoint in checkpoint_dir.glob(pattern):
        try:
            checkpoint.unlink()
        except Exception:
            pass
