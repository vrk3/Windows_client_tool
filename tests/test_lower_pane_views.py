# tests/test_lower_pane_views.py
from unittest.mock import patch, MagicMock
import socket


def _make_conn(pid, sock_type=socket.SOCK_STREAM,
               laddr=("127.0.0.1", 8080), raddr=("10.0.0.1", 443), status="ESTABLISHED"):
    c = MagicMock()
    c.pid = pid
    c.type = sock_type
    c.laddr = MagicMock(ip=laddr[0], port=laddr[1]) if laddr else None
    c.raddr = MagicMock(ip=raddr[0], port=raddr[1]) if raddr else None
    c.status = status
    return c


def test_network_view_filters_by_pid(qapp):
    from modules.process_explorer.lower_pane.network_view import NetworkView
    view = NetworkView()
    conns = [_make_conn(1234), _make_conn(9999)]
    with patch("modules.process_explorer.lower_pane.network_view.psutil.net_connections",
               return_value=conns):
        view.load_pid(1234)
    assert view._table.rowCount() == 1


def test_network_view_tcp_udp_label(qapp):
    from modules.process_explorer.lower_pane.network_view import NetworkView
    view = NetworkView()
    conns = [
        _make_conn(1, socket.SOCK_STREAM),
        _make_conn(1, socket.SOCK_DGRAM),
    ]
    with patch("modules.process_explorer.lower_pane.network_view.psutil.net_connections",
               return_value=conns):
        view.load_pid(1)
    assert view._table.item(0, 0).text() == "TCP"
    assert view._table.item(1, 0).text() == "UDP"


def test_network_view_access_denied_clears_table(qapp):
    from modules.process_explorer.lower_pane.network_view import NetworkView
    import psutil
    view = NetworkView()
    with patch("modules.process_explorer.lower_pane.network_view.psutil.net_connections",
               side_effect=psutil.AccessDenied(0)):
        view.load_pid(1234)
    assert view._table.rowCount() == 0


def test_thread_view_populates_rows(qapp):
    from modules.process_explorer.lower_pane.thread_view import ThreadView
    view = ThreadView()
    mock_thread = MagicMock(id=100, user_time=0.5, system_time=0.1)
    mock_proc = MagicMock()
    mock_proc.threads.return_value = [mock_thread]
    with patch("modules.process_explorer.lower_pane.thread_view.psutil.Process",
               return_value=mock_proc):
        view.load_pid(1234)
    assert view._table.rowCount() == 1
    assert view._table.item(0, 0).text() == "100"


def test_thread_view_no_such_process(qapp):
    from modules.process_explorer.lower_pane.thread_view import ThreadView
    import psutil
    view = ThreadView()
    with patch("modules.process_explorer.lower_pane.thread_view.psutil.Process",
               side_effect=psutil.NoSuchProcess(1234)):
        view.load_pid(1234)
    assert view._table.rowCount() == 0


def test_thread_view_refresh_reuses_pid(qapp):
    from modules.process_explorer.lower_pane.thread_view import ThreadView
    view = ThreadView()
    mock_thread = MagicMock(id=101, user_time=1.0, system_time=0.2)
    mock_proc = MagicMock()
    mock_proc.threads.return_value = [mock_thread]
    with patch("modules.process_explorer.lower_pane.thread_view.psutil.Process",
               return_value=mock_proc):
        view.load_pid(5678)
        view._refresh()
    assert view._pid == 5678
    assert view._table.rowCount() == 1
