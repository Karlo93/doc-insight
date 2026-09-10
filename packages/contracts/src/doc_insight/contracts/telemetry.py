"""Stage observation leaves the wrapped operation's result and errors unchanged."""

from contextlib import AbstractContextManager
from typing import Protocol


class StageObserver(Protocol):
    def stage(self, name: str) -> AbstractContextManager[None]: ...
