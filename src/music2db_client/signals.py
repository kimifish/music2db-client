from __future__ import annotations

import signal
from collections.abc import Callable


class GracefulKiller:
    def __init__(self, kill_targets: list[Callable[[], None]] | None = None) -> None:
        self.kill_now = False
        self._kill_targets = kill_targets or []
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum: int, frame: object | None) -> None:
        self.kill_now = True
        for target in self._kill_targets:
            target()
