import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Lightweight in-process pub/sub system.

    Catches per-subscriber exceptions and continues dispatching.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable) -> None:
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        try:
            self._subscribers[event_type].remove(callback)
        except ValueError:
            pass

    def publish(self, event_type: str, data: object) -> None:
        for callback in self._subscribers.get(event_type, []):
            try:
                callback(data)
            except Exception:
                logger.exception(
                    "EventBus: subscriber %r raised on event %s",
                    callback,
                    event_type,
                )

    def publish_async(self, event_type: str, data: object) -> None:
        """Marshal event to Qt main thread via QTimer.singleShot.
        Requires a running QApplication."""
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, lambda: self.publish(event_type, data))
