"""The Details table's columns.

Forty of them, declared as data rather than as forty branches of a `data()`
method. These tests are about the two rules that run through all of them:
sort on the value, and never state a number we do not have.
"""
import os

import pytest

from core.procengine.columns import (
    BY_KEY, COLUMNS, DEFAULT_KEYS, GROUPS, UNKNOWN, cell_text, cell_tooltip,
    fmt_bytes, fmt_count, fmt_cpu_time, fmt_percent, fmt_rate,
    fmt_start_time, sort_key,
)
from core.procengine.snapshot import SnapshotSource


@pytest.fixture(scope="module")
def snapshot():
    source = SnapshotSource()
    source.read()
    return source.read()


# ---- the set itself -----------------------------------------------------

def test_there_are_the_forty_or_so_columns_task_manager_has():
    assert len(COLUMNS) >= 40


def test_every_key_is_unique():
    keys = [column.key for column in COLUMNS]
    assert len(keys) == len(set(keys))


def test_every_title_is_unique():
    """Two columns with one name is unusable in a header menu."""
    titles = [column.title for column in COLUMNS]
    assert len(titles) == len(set(titles))


def test_the_default_set_is_small_enough_to_fit_on_screen():
    """Showing all forty by default is not a feature, it is a wall."""
    assert 5 <= len(DEFAULT_KEYS) <= 12


def test_name_and_pid_are_shown_by_default():
    assert "name" in DEFAULT_KEYS and "pid" in DEFAULT_KEYS


def test_every_column_is_in_a_group_for_the_header_menu():
    assert all(column.group for column in COLUMNS)
    assert len(GROUPS) >= 4


def test_every_column_explains_itself():
    """The header menu shows these; a list of forty bare names is a puzzle."""
    assert all(column.description for column in COLUMNS)


def test_task_managers_memory_column_is_the_private_working_set():
    """The one people read as "Memory". Using the working set instead
    overstates every process that maps a shared DLL, which is all of them."""
    assert BY_KEY["memory"].value.__closure__ is not None
    from core.procengine.ntquery import ProcessRaw
    assert "working_set_private" in ProcessRaw.__annotations__


# ---- formatting ---------------------------------------------------------

def test_bytes_are_scaled_to_a_readable_unit():
    assert fmt_bytes(512) == "512 B"
    assert fmt_bytes(2048) == "2.0 KB"
    assert fmt_bytes(5 * 1024**3) == "5.0 GB"


def test_an_unknown_byte_count_is_a_dash_not_a_zero():
    assert fmt_bytes(None) == UNKNOWN


def test_an_idle_process_shows_nothing_rather_than_zero():
    """A column of "0 B/s" down 275 rows is noise. Task Manager blanks it."""
    assert fmt_rate(0) == ""
    assert fmt_percent(0.0) == ""


def test_an_unmeasured_rate_is_a_dash_which_is_not_the_same_as_idle():
    """The distinction the whole engine is built to keep: "idle" and "not
    measured yet" must not look the same."""
    assert fmt_rate(None) == UNKNOWN
    assert fmt_percent(None) == UNKNOWN
    assert fmt_rate(None) != fmt_rate(0)


def test_cpu_time_reads_as_a_duration():
    assert fmt_cpu_time(10_000_000 * 61) == "0:01:01"


def test_counts_carry_thousands_separators():
    assert fmt_count(1234567) == "1,234,567"


def test_a_start_time_of_zero_is_not_1601():
    """Pid 0 and pid 4 report no create time. Rendering the FILETIME epoch
    would put "1601-01-01" in the table."""
    assert fmt_start_time(0) == UNKNOWN


def test_a_real_start_time_renders():
    """Our own process started at a sane moment."""
    from core.procengine.ntquery import system_processes

    mine = next(row for row in system_processes() if row.pid == os.getpid())
    rendered = fmt_start_time(mine.create_time)
    assert rendered != UNKNOWN
    assert rendered.startswith("20")


# ---- sorting ------------------------------------------------------------

def test_sorting_is_on_the_value_not_the_text(snapshot):
    """The TreeSize rule. "9 B" above "10 GB" is what string sorting does."""
    column = BY_KEY["memory"]
    infos = list(snapshot.by_pid.values())
    ordered = sorted(infos, key=lambda info: sort_key(column, info))
    values = [column.value(info) for info in ordered]
    assert values == sorted(values)


def test_unknown_values_sort_last_rather_than_first(snapshot):
    column = BY_KEY["path"]
    infos = list(snapshot.by_pid.values())
    ordered = sorted(infos, key=lambda info: sort_key(column, info))
    known = [column.value(info) is not None for info in ordered]
    assert known == sorted(known, reverse=True)


def test_sorting_never_compares_none_with_a_number(snapshot):
    """A TypeError raised inside a Qt sort happens inside a reimplemented
    virtual, where it cannot be caught and the process dies."""
    for column in COLUMNS:
        infos = list(snapshot.by_pid.values())
        sorted(infos, key=lambda info: sort_key(column, info))


def test_text_sorts_case_insensitively(snapshot):
    column = BY_KEY["name"]
    infos = list(snapshot.by_pid.values())
    ordered = [column.value(info) or ""
               for info in sorted(infos,
                                  key=lambda info: sort_key(column, info))]
    assert ordered == sorted(ordered, key=str.lower)


# ---- against the real machine -------------------------------------------

def test_every_column_renders_for_every_process(snapshot):
    """The check that would catch a getter naming a field that moved."""
    for info in snapshot.by_pid.values():
        for column in COLUMNS:
            assert isinstance(cell_text(column, info), str)


def test_a_refused_value_shows_a_dash_and_explains_itself_on_hover(snapshot):
    """Unelevated, about half the machine refuses its path. Those cells must
    say why rather than going blank."""
    refused = [info for info in snapshot.by_pid.values()
               if info.details.path is None]
    assert refused, "nothing was refused; run this test unelevated"

    column = BY_KEY["path"]
    info = refused[0]
    assert cell_text(column, info) == UNKNOWN
    tooltip = cell_tooltip(column, info)
    assert tooltip, "it went blank without saying why"
    assert column.title in tooltip, "the tooltip does not say which column"
    assert len(tooltip) > len(column.title) + 2, "there is no reason in it"


def test_a_known_value_has_no_tooltip(snapshot):
    """A tooltip on every cell is noise; it means something only where the
    value is missing."""
    mine = snapshot.by_pid[os.getpid()]
    assert cell_tooltip(BY_KEY["pid"], mine) is None


def test_no_column_ever_renders_a_bare_zero_for_something_unknown(snapshot):
    """The rule, checked across the whole machine: a refused reading must
    never come out as "0"."""
    for info in snapshot.by_pid.values():
        for column in COLUMNS:
            if column.value(info) is None:
                assert cell_text(column, info) in (UNKNOWN, ""), \
                    f"{column.key} rendered an unknown as a value"


# ---- Qt-free ------------------------------------------------------------

def test_the_columns_do_not_import_qt():
    import inspect

    from core.procengine import columns

    assert "PyQt6" not in inspect.getsource(columns)
