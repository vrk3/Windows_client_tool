import pytest
from core.event_bus import EventBus


def test_subscribe_and_publish():
    bus = EventBus()
    received = []
    bus.subscribe("test.event", lambda data: received.append(data))
    bus.publish("test.event", {"key": "value"})
    assert received == [{"key": "value"}]


def test_multiple_subscribers():
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("test.event", lambda d: results_a.append(d))
    bus.subscribe("test.event", lambda d: results_b.append(d))
    bus.publish("test.event", "hello")
    assert results_a == ["hello"]
    assert results_b == ["hello"]


def test_unsubscribe():
    bus = EventBus()
    received = []
    callback = lambda d: received.append(d)
    bus.subscribe("test.event", callback)
    bus.unsubscribe("test.event", callback)
    bus.publish("test.event", "ignored")
    assert received == []


def test_publish_no_subscribers_does_not_raise():
    bus = EventBus()
    bus.publish("nonexistent.event", {})  # Should not raise


def test_subscriber_exception_does_not_break_others():
    bus = EventBus()
    results = []

    def bad_callback(data):
        raise ValueError("I broke")

    def good_callback(data):
        results.append(data)

    bus.subscribe("test.event", bad_callback)
    bus.subscribe("test.event", good_callback)
    bus.publish("test.event", "data")
    assert results == ["data"]


def test_different_event_types_are_isolated():
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("event.a", lambda d: results_a.append(d))
    bus.subscribe("event.b", lambda d: results_b.append(d))
    bus.publish("event.a", "a_data")
    assert results_a == ["a_data"]
    assert results_b == []


def test_unsubscribe_nonexistent_callback_does_not_raise():
    bus = EventBus()
    bus.unsubscribe("test.event", lambda d: None)  # Should not raise


def test_publish_with_typed_dataclass():
    from core.events import ConfigChangedData
    bus = EventBus()
    received = []
    bus.subscribe("config.changed", lambda d: received.append(d))
    payload = ConfigChangedData(key="app.theme", old_value="light", new_value="dark")
    bus.publish("config.changed", payload)
    assert len(received) == 1
    assert received[0].key == "app.theme"
