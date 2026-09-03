"""The modules loaded in a process.

The point that carries the file: a process we cannot read returns `None`
with a reason, never `[]`. A running process has loaded libraries by
definition, so an empty list is not a possible state -- which makes it
exactly the kind of wrong answer that looks like an answer.
"""
import os
import time


from core.procengine.modinfo import (
    loaded_modules, version_info,
)

MY_PID = os.getpid()


# ---- reading a process --------------------------------------------------

def test_our_own_modules_are_listed():
    modules, reason = loaded_modules(MY_PID)
    assert reason is None
    assert modules and len(modules) > 5


def test_the_executable_itself_is_among_them():
    modules, _reason = loaded_modules(MY_PID)
    names = {module.name.lower() for module in modules}
    assert "ntdll.dll" in names
    assert any(name.endswith(".exe") for name in names)


def test_every_module_has_a_base_and_a_size():
    """Both were always shown, but size was hardcoded to 0 before this --
    a column of zeros that looked like a measurement."""
    modules, _reason = loaded_modules(MY_PID)
    for module in modules:
        assert module.base > 0, module.name
        assert module.size > 0, module.name


def test_modules_carry_their_company_and_version():
    """Also always shown, and always empty before this."""
    modules, _reason = loaded_modules(MY_PID)
    described = [m for m in modules if m.company and m.version]
    assert len(described) > len(modules) * 0.5, \
        "most system DLLs carry a version resource"


def test_a_process_we_cannot_read_is_none_not_empty():
    """pid 4 is the kernel and refuses. An empty list would say it has
    loaded nothing, which is impossible."""
    modules, reason = loaded_modules(4)
    assert modules is None
    assert reason and "denied" in reason.lower()


def test_a_dead_pid_is_none_with_a_reason():
    modules, reason = loaded_modules(999_999)
    assert modules is None and reason


def test_skipping_the_version_pass_is_cheaper_and_says_less():
    modules, _reason = loaded_modules(MY_PID, with_version=False)
    assert modules
    assert all(module.company is None for module in modules)
    assert all(module.size > 0 for module in modules)


# ---- the version cache --------------------------------------------------

def test_a_version_resource_is_read():
    company, version, description = version_info(
        os.path.join(os.environ["SystemRoot"], "System32", "kernel32.dll"))
    assert company and "Microsoft" in company
    assert version


def test_a_file_with_no_version_resource_is_none_not_blank(tmp_path):
    plain = tmp_path / "nothing.dll"
    plain.write_bytes(b"not a pe")
    company, version, description = version_info(str(plain))
    assert company is None and version is None and description is None


def test_the_cache_makes_a_second_read_free():
    """A machine runs the same hundred system DLLs in every process, so
    without this the pane re-reads kernel32's resource once per process."""
    loaded_modules(MY_PID)                    # warm
    started = time.perf_counter()
    loaded_modules(MY_PID)
    assert time.perf_counter() - started < 0.2


def test_a_missing_file_does_not_raise():
    assert version_info(r"C:\definitely\not\here.dll") == (None, None, None)


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from core.procengine import modinfo

    assert "PyQt6" not in inspect.getsource(modinfo)
