"""Discover usable hardware and bound parallel work by CPU and memory."""

from functools import lru_cache
import os
import platform
import subprocess
from threading import Lock
import math

import cv2

_configured = False
_configure_lock = Lock()


def cpu_count():
    if hasattr(os, "process_cpu_count"):
        return max(1, os.process_cpu_count() or 1)
    if hasattr(os, "sched_getaffinity"):
        return max(1, len(os.sched_getaffinity(0)))
    return max(1, os.cpu_count() or 1)


@lru_cache(maxsize=1)
def memory_bytes():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        if platform.system() == "Darwin":
            try:
                return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=2))
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        if platform.system() == "Windows":
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            *[(name, ctypes.c_ulonglong) for name in
                              ("total", "available", "page_total", "page_available",
                               "virtual_total", "virtual_available", "extended")]]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total)
    return 4 * 1024**3


@lru_cache(maxsize=1)
def gpu_devices():
    """Only report GPU devices with an available OpenCL compiler/driver."""
    try:
        import pyopencl as cl
        devices = []
        for provider in cl.get_platforms():
            for device in provider.get_devices():
                if device.type & cl.device_type.GPU and device.available and device.compiler_available:
                    devices.append(device)
        return sorted(devices, key=lambda d: d.max_compute_units * d.max_clock_frequency,
                      reverse=True)
    except Exception:
        return []


def worker_count(width=2048, height=2048, is_raw=False, requested=None):
    # Reserve most RAM for the renderer, GPU buffers, the desktop, and the OS.
    # Full-size decode buffers dominate even though detection is downsampled.
    # Reused RAW denoising planes remove roughly two full-frame float buffers.
    # Keep a larger fixed decoder/colour-conversion reserve for LibRaw and
    # OpenCV's internal allocations while allowing safe parallelism on medium
    # sensors.
    per_frame = width * height * (40 if is_raw else 18) + 240 * 1024**2
    by_memory = max(1, (memory_bytes() // 4) // per_frame)
    return max(1, min(cpu_count(), 4, by_memory, requested or 4))


def adaptive_checkpoint_interval(frame_bytes: int, base: int = 20,
                                 target_bytes: int = 128 * 1024**2,
                                 max_multiplier: int = 6) -> int:
    """Choose a checkpoint cadence that bounds checkpoint I/O for large stacks.

    A checkpoint serializes the complete float accumulator. Keeping the old
    frame cadence for a 1 GB canvas can spend more time writing checkpoints
    than stacking. The bounded multiplier still provides regular recovery for
    long jobs while scaling writes with the amount of data being copied.
    """
    base = max(1, int(base))
    frame_bytes = max(0, int(frame_bytes))
    multiplier = max(1, math.ceil(frame_bytes / max(1, int(target_bytes))))
    return base * min(max(1, int(max_multiplier)), multiplier)


def configure_native_threads():
    global _configured
    with _configure_lock:
        if not _configured:
            # Avoid multiplying OpenCV's full-machine pool by every frame worker.
            cv2.setNumThreads(max(1, cpu_count() // min(4, cpu_count())))
            _configured = True


def system_capabilities():
    return {
        "cpu_count": cpu_count(), "memory_bytes": memory_bytes(),
        "max_cpu_workers": min(4, cpu_count()),
        "gpus": [{"name": d.name, "vendor": d.vendor, "api": "OpenCL",
                  "memory_bytes": int(d.global_mem_size)} for d in gpu_devices()],
    }
