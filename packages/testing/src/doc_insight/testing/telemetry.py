"""Deterministic stage observation without clocks, providers or exporters."""

from collections.abc import Iterator
from contextlib import contextmanager


class FakeStageObserver:
    def __init__(self) -> None:
        self.completed: list[tuple[str, str]] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        status = "processed"
        try:
            yield
        except BaseException:
            status = "failed"
            raise
        finally:
            self.completed.append((name, status))
