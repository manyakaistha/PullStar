"""Ordered, bounded frame workers with cooperative cancellation."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from core.cancellation import check_cancelled


def ordered_map(function, items, workers=1, cancel_check=None):
    """Keep at most ``workers`` results in flight and consume in source order."""
    if workers <= 1:
        for item in items:
            check_cancelled(cancel_check)
            yield function(item)
        return
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="staraligner-frame")
    pending = deque()
    iterator = iter(items)
    try:
        for _ in range(workers):
            try:
                pending.append(pool.submit(function, next(iterator)))
            except StopIteration:
                break
        while pending:
            check_cancelled(cancel_check)
            future = pending.popleft()
            while True:
                check_cancelled(cancel_check)
                try:
                    result = future.result(timeout=0.05)
                    break
                except TimeoutError:
                    if future.done():
                        raise
            check_cancelled(cancel_check)
            yield result
            del result
            try:
                pending.append(pool.submit(function, next(iterator)))
            except StopIteration:
                pass
    finally:
        for future in pending:
            future.cancel()
        # Returning "cancelled" means in-flight workers have exited too.
        pool.shutdown(wait=True, cancel_futures=True)
