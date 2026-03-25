from core.module_groups import ModuleGroup
from core.base_module import BaseModule


def test_module_group_constants_exist():
    assert ModuleGroup.DIAGNOSE == "DIAGNOSE"
    assert ModuleGroup.SYSTEM == "SYSTEM"
    assert ModuleGroup.MANAGE == "MANAGE"
    assert ModuleGroup.OPTIMIZE == "OPTIMIZE"
    assert ModuleGroup.TOOLS == "TOOLS"
    assert ModuleGroup.PROCESS == "PROCESS"


def test_base_module_has_group_annotation():
    assert "group" in BaseModule.__annotations__
