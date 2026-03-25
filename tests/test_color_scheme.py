from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.color_scheme import get_row_color, ProcessColor


def _node(**kwargs):
    defaults = dict(pid=100, name="test.exe", exe="", cmdline="", user="testuser",
                    status="running", parent_pid=0)
    defaults.update(kwargs)
    return ProcessNode(**defaults)


def test_system_process_color():
    node = _node(is_system=True)
    assert get_row_color(node) == ProcessColor.SYSTEM

def test_service_color():
    node = _node(is_service=True)
    assert get_row_color(node) == ProcessColor.SERVICE

def test_dotnet_color():
    node = _node(is_dotnet=True)
    assert get_row_color(node) == ProcessColor.DOTNET

def test_suspended_color():
    node = _node(is_suspended=True)
    assert get_row_color(node) == ProcessColor.SUSPENDED

def test_gpu_color():
    node = _node(gpu_percent=15.0)
    assert get_row_color(node) == ProcessColor.GPU

def test_own_process_color():
    node = _node()
    assert get_row_color(node) == ProcessColor.DEFAULT

def test_system_takes_priority_over_service():
    node = _node(is_system=True, is_service=True)
    assert get_row_color(node) == ProcessColor.SYSTEM
