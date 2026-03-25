import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertRule:
    def __init__(self, counter: str, operator: str, threshold: float, duration_sec: int, enabled: bool = True):
        self.counter = counter
        self.operator = operator  # ">" or "<"
        self.threshold = threshold
        self.duration_sec = duration_sec
        self.enabled = enabled
        self._triggered_since: Optional[float] = None
        self._fired = False

    def check(self, value: float) -> Optional[str]:
        """Check value against threshold. Returns alert message or None."""
        if not self.enabled:
            return None

        triggered = False
        if self.operator == ">" and value > self.threshold:
            triggered = True
        elif self.operator == "<" and value < self.threshold:
            triggered = True

        if triggered:
            if self._triggered_since is None:
                self._triggered_since = time.time()
            elapsed = time.time() - self._triggered_since
            if elapsed >= self.duration_sec and not self._fired:
                self._fired = True
                return f"{self.counter} {self.operator} {self.threshold} for {self.duration_sec}s (current: {value:.1f})"
        else:
            self._triggered_since = None
            self._fired = False

        return None

    def reset(self) -> None:
        self._triggered_since = None
        self._fired = False
