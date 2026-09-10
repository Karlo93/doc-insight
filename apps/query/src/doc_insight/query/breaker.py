"""Generation tickets keep old in-flight calls from settling a recovery probe."""

from collections.abc import Callable
from threading import Lock
from time import monotonic


class CircuitBreaker:
    def __init__(
        self, failures: int, seconds: float, clock: Callable[[], float] = monotonic
    ):
        self.limit, self.seconds, self.clock = failures, seconds, clock
        self.failures, self.epoch = 0, 0
        self.opened: float | None = None
        self.probing = False
        self.lock = Lock()

    def acquire(self) -> int | None:
        with self.lock:
            if self.opened is not None:
                if self.clock() - self.opened < self.seconds or self.probing:
                    return None
                self.probing = True
            return self.epoch

    def finish(self, ticket: int, success: bool) -> None:
        with self.lock:
            if ticket != self.epoch:
                return
            if success:
                self.failures = 0
                if self.probing:
                    self.opened, self.probing = None, False
                    self.epoch += 1
            else:
                self.failures += 1
                if self.probing or self.failures >= self.limit:
                    self.opened, self.probing = self.clock(), False
                    self.epoch += 1
