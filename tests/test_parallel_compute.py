from threading import Event, Lock, Thread
from time import sleep

import pytest

from core import compute
from core.cancellation import CancellationToken, OperationCancelled
from core.parallel import ordered_map


def test_parallel_results_stay_ordered_and_work_is_bounded():
    active, peak = 0, 0
    lock = Lock()

    def work(index):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        sleep(0.002 * (3 - index % 3))
        with lock:
            active -= 1
        return index * 2

    assert list(ordered_map(work, range(12), workers=3)) == list(range(0, 24, 2))
    assert 1 < peak <= 3
    assert active == 0


def test_cancellation_waits_for_all_parallel_workers_to_stop():
    token = CancellationToken()
    entered = Event()
    lock = Lock()
    active, started = 0, 0
    errors = []

    def work(index):
        nonlocal active, started
        with lock:
            active += 1
            started += 1
            if active == 3:
                entered.set()
        try:
            while True:
                token.check()
                sleep(0.002)
        finally:
            with lock:
                active -= 1

    def consume():
        try:
            list(ordered_map(work, range(100), workers=3, cancel_check=token.check))
        except OperationCancelled as error:
            errors.append(error)

    thread = Thread(target=consume)
    thread.start()
    try:
        assert entered.wait(2)
    finally:
        token.cancel()
        thread.join(2)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert active == 0
    assert started == 3


def test_worker_limits_follow_cpu_and_image_memory(monkeypatch):
    monkeypatch.setattr(compute, "cpu_count", lambda: 10)
    monkeypatch.setattr(compute, "memory_bytes", lambda: 16 * 1024**3)
    assert compute.worker_count(4080, 3072) == 4
    assert compute.worker_count(8160, 6120, is_raw=True) == 1
    assert compute.worker_count(4080, 3072, requested=1) == 1
    monkeypatch.setattr(compute, "memory_bytes", lambda: 8 * 1024**3)
    assert compute.worker_count(4096, 3072, is_raw=True) == 2
    monkeypatch.setattr(compute, "memory_bytes", lambda: 2 * 1024**3)
    assert compute.worker_count(8160, 6120, is_raw=True) == 1
    monkeypatch.setattr(compute, "cpu_count", lambda: 1)
    assert compute.worker_count(100, 100) == 1


def test_worker_exceptions_are_not_hidden():
    def work(index):
        if index == 2:
            raise ValueError("bad source")
        return index
    with pytest.raises(ValueError, match="bad source"):
        list(ordered_map(work, range(5), workers=3))
