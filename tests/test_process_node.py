from modules.process_explorer.process_node import ProcessNode

def test_process_node_creation():
    node = ProcessNode(
        pid=1234, name="chrome.exe", exe=r"C:\Program Files\Google\Chrome\chrome.exe",
        cmdline="chrome.exe --type=renderer", user="testuser", status="running",
        parent_pid=1000, children=[],
        cpu_percent=2.5, memory_rss=52428800, memory_vms=104857600,
        disk_read_bps=0.0, disk_write_bps=1024.0,
        net_send_bps=512.0, net_recv_bps=2048.0, gpu_percent=0.0,
        is_system=False, is_service=False, is_dotnet=False, is_suspended=False,
        integrity_level="Medium", sha256=None, vt_score=None,
    )
    assert node.pid == 1234
    assert node.name == "chrome.exe"
    assert node.children == []
    assert node.sha256 is None

def test_process_node_children_independent():
    """Each node gets its own children list."""
    a = ProcessNode(pid=1, name="a.exe", exe="", cmdline="", user="", status="running",
                    parent_pid=0, children=[],
                    cpu_percent=0, memory_rss=0, memory_vms=0,
                    disk_read_bps=0, disk_write_bps=0,
                    net_send_bps=0, net_recv_bps=0, gpu_percent=0,
                    is_system=False, is_service=False, is_dotnet=False, is_suspended=False,
                    integrity_level="Medium", sha256=None, vt_score=None)
    b = ProcessNode(pid=2, name="b.exe", exe="", cmdline="", user="", status="running",
                    parent_pid=0, children=[],
                    cpu_percent=0, memory_rss=0, memory_vms=0,
                    disk_read_bps=0, disk_write_bps=0,
                    net_send_bps=0, net_recv_bps=0, gpu_percent=0,
                    is_system=False, is_service=False, is_dotnet=False, is_suspended=False,
                    integrity_level="Medium", sha256=None, vt_score=None)
    a.children.append(b)
    assert len(a.children) == 1
    assert b.children == []
