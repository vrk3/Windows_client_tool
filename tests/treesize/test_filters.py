from modules.treesize.scan.filters import FilterSet
from modules.treesize.store.node_store import DIR, HIDDEN, REPARSE


def test_no_rules_excludes_nothing():
    f = FilterSet()
    assert f.excludes("anything.txt", 100, 0) is False


def test_glob_exclusion_matches_name():
    f = FilterSet(exclude_globs=("*.tmp",))
    assert f.excludes("cache.tmp", 100, 0) is True
    assert f.excludes("cache.txt", 100, 0) is False


def test_glob_matching_is_case_insensitive():
    f = FilterSet(exclude_globs=("*.TMP",))
    assert f.excludes("cache.tmp", 100, 0) is True


def test_min_size_excludes_smaller_files():
    f = FilterSet(min_size=1000)
    assert f.excludes("small.bin", 999, 0) is True
    assert f.excludes("big.bin", 1000, 0) is False


def test_max_size_excludes_larger_files():
    f = FilterSet(max_size=1000)
    assert f.excludes("big.bin", 1001, 0) is True


def test_size_rules_never_exclude_directories():
    f = FilterSet(min_size=1000)
    assert f.excludes("emptydir", 0, DIR) is False


def test_excluded_count_accumulates():
    f = FilterSet(exclude_globs=("*.tmp",))
    f.excludes("a.tmp", 1, 0)
    f.excludes("b.tmp", 1, 0)
    f.excludes("c.txt", 1, 0)
    assert f.excluded_count == 2


def test_exclude_hidden_reads_the_node_hidden_flag():
    f = FilterSet(exclude_hidden=True)
    assert f.excludes("secret.txt", 100, HIDDEN) is True
    assert f.excludes("plain.txt", 100, 0) is False


def test_exclude_hidden_does_not_catch_reparse_points():
    """HIDDEN and REPARSE are distinct node flags; a junction is not hidden."""
    f = FilterSet(exclude_hidden=True)
    assert f.excludes("junction", 0, DIR | REPARSE) is False


def test_hidden_rule_is_off_by_default():
    f = FilterSet()
    assert f.excludes("secret.txt", 100, HIDDEN) is False


def test_one_entry_counts_once_even_when_several_rules_match():
    f = FilterSet(exclude_globs=("*.tmp",), min_size=1000)
    assert f.excludes("tiny.tmp", 1, 0) is True
    assert f.excluded_count == 1
