import logging
import threading
from collections import defaultdict
from typing import Callable, List

logger = logging.getLogger(__name__)


class EventBus:
    """Lightweight in-process pub/sub system.

    Catches per-subscriber exceptions and continues dispatching.

    Two things this class has to get right, both learned the hard way:

    * **Dispatch runs over a SNAPSHOT of the subscriber list.** Iterating
      the live list meant a handler that unsubscribed itself shifted every
      later index down, and the loop silently skipped whichever subscriber
      moved into the slot it had just left. A handler that subscribed
      during dispatch was, symmetrically, invoked for the event already in
      flight.

    * **The subscriber lists are guarded by a lock.** `publish` is
      reachable from worker threads — only `publish_async` marshals to the
      GUI thread — so a publish can be reading the list while another
      thread appends to it. The lock is held only while the snapshot is
      taken, never while a subscriber runs: a handler that publishes
      would otherwise deadlock against itself, and a slow one would block
      every other thread's publish.
    """

    def __init__(self):
        self._subscribers: dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        with self._lock:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        with self._lock:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                logger.debug(
                    "unsubscribe: %r was not subscribed to %s", callback, event_type)

    def publish(self, event_type: str, data: object) -> None:
        with self._lock:
            listeners = list(self._subscribers.get(event_type, ()))

        for callback in listeners:
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
