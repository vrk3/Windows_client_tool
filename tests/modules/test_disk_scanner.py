import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))


def test_disk_node_defaults():
    from modules.treesize.disk_scanner import DiskNode
    node = DiskNode(path="/test", name="test", size=500, is_dir=True)
    assert node.path == "/test"
    assert node.size == 500
    assert node.is_dir is True
    assert node.file_count == 0
    assert node.children == []
    assert node.parent is None


def test_disk_node_parent_link():
    from modules.treesize.disk_scanner import DiskNode
    parent = DiskNode(path="/root", name="root", size=0, is_dir=True)
    child = DiskNode(path="/root/a", name="a", size=100, is_dir=False, parent=parent)
    assert child.parent is parent


def test_format_size_bytes():
    from modules.treesize.disk_tree_model import format_size
    result = format_size(512)
    assert "B" in result


def test_format_size_mb():
    from modules.treesize.disk_tree_model import format_size
    result = format_size(2 * 1024 * 1024)
    assert "MB" in result


def test_format_size_gb():
    from modules.treesize.disk_tree_model import format_size
    result = format_size(3 * 1024 ** 3)
    assert "GB" in result


def test_format_size_tb():
    from modules.treesize.disk_tree_model import format_size
    result = format_size(2 * 1024 ** 4)
    assert "TB" in result
