from ui.notification_tray import NotificationTray, NotificationItem


def test_add_notification():
    tray = NotificationTray()
    item = NotificationItem(title="Test", message="Something happened", level="info")
    tray.add_notification(item)
    assert len(tray._notifications) == 1
    assert tray._notifications[0].title == "Test"


def test_clear_all():
    tray = NotificationTray()
    tray.add_notification(NotificationItem("A", "msg"))
    tray.add_notification(NotificationItem("B", "msg"))
    tray.clear_all()
    assert len(tray._notifications) == 0


def test_max_notifications():
    tray = NotificationTray()
    for i in range(60):
        tray.add_notification(NotificationItem(f"N{i}", "msg"))
    assert len(tray._notifications) == tray.MAX_VISIBLE
