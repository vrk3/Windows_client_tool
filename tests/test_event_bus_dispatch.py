"""EventBus has to survive a subscriber that changes the subscriber list.

`publish` iterated `self._subscribers.get(event_type, [])` directly — the
live list, not a copy. A handler that unsubscribes itself while it runs
shifts every later index down by one, and the iteration skips whichever
subscriber moved into the slot it just left. Silently: the skipped handler
simply never hears about the event.

There is also no lock, and `publish` is reachable from worker threads —
only `publish_async` marshals to the GUI thread.
"""
import threading

from core.event_bus import EventBus


def test_a_subscriber_that_unsubscribes_itself_does_not_hide_the_next_one():
    bus = EventBus()
    heard = []

    def first(data):
        heard.append("first")
        bus.unsubscribe("topic", first)

    def second(data):
        heard.append("second")

    bus.subscribe("topic", first)
    bus.subscribe("topic", second)

    bus.publish("topic", None)

    assert heard == ["first", "second"], (
        "the second subscriber was skipped when the first removed itself")


def test_a_subscriber_added_during_dispatch_does_not_hear_the_event_in_flight():
    """Otherwise a handler that subscribes on its first call is invoked
    twice for the same event."""
    bus = EventBus()
    heard = []

    def late(data):
        heard.append("late")

    def first(data):
        heard.append("first")
        bus.subscribe("topic", late)

    bus.subscribe("topic", first)
    bus.publish("topic", None)

    assert heard == ["first"]

    bus.publish("topic", None)
    assert heard == ["first", "first", "late"]


def test_a_raising_subscriber_does_not_stop_the_others():
    bus = EventBus()
    heard = []

    bus.subscribe("topic", lambda _d: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe("topic", lambda _d: heard.append("after"))

    bus.publish("topic", None)

    assert heard == ["after"]


def test_unsubscribing_something_that_was_never_subscribed_is_not_an_error():
    bus = EventBus()
    bus.unsubscribe("topic", lambda _d: None)   # must not raise


def test_publishing_from_several_threads_at_once_delivers_everything():
    """Workers publish from their own threads; only publish_async marshals
    to the GUI thread. Without a lock the subscriber list can be read while
    another thread is appending to it."""
    bus = EventBus()
    heard = []
    lock = threading.Lock()

    def record(data):
        with lock:
            heard.append(data)

    bus.subscribe("topic", record)

    threads = [threading.Thread(target=bus.publish, args=("topic", n))
               for n in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(heard) == list(range(40))


def test_subscribing_while_another_thread_publishes_does_not_raise():
    bus = EventBus()
    stop = threading.Event()

    def publisher():
        while not stop.is_set():
            bus.publish("topic", None)

    bus.subscribe("topic", lambda _d: None)
    worker = threading.Thread(target=publisher)
    worker.start()
    try:
        for _ in range(200):
            handler = lambda _d: None  # noqa: E731 - a distinct object each time
            bus.subscribe("topic", handler)
            bus.unsubscribe("topic", handler)
    finally:
        stop.set()
        worker.join()
