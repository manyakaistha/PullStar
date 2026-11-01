"""Cooperative cancellation shared by detection and rendering workers."""

from threading import Event, RLock


class OperationCancelled(Exception):
    """An action stopped at the user's request, rather than failing."""


class CancellationToken:
    def __init__(self):
        self._event = Event()
        self._lock = RLock()
        self._committed = False

    @property
    def cancelled(self):
        return self._event.is_set()

    def check(self):
        if self.cancelled:
            raise OperationCancelled("Cancelled by user")

    def cancel(self):
        with self._lock:
            if self._committed or self._event.is_set():
                return False
            self._event.set()
            return True

    def commit(self, action):
        """Serialize final publication with cancellation's point of acceptance."""
        with self._lock:
            self.check()
            result = action()
            self._committed = True
            return result


def check_cancelled(cancel_check=None):
    if cancel_check is not None:
        cancel_check()
