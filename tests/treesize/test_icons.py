"""Per-extension shell icons (spec 5.4)."""
import pytest
from PyQt6.QtGui import QIcon

from modules.treesize.ui.icons import IconProvider


def test_known_extensions_get_an_icon(qapp):
    provider = IconProvider()
    for name in ("setup.exe", "notes.txt", "photo.png", "archive.zip"):
        assert isinstance(provider.for_name(name), QIcon)
        assert not provider.for_name(name).isNull()


def test_folders_get_a_folder_icon(qapp):
    provider = IconProvider()
    assert not provider.folder().isNull()


def test_icons_are_cached_per_extension_not_per_file(qapp):
    """Half a million files, a few hundred extensions. Caching per file would
    cost more than the node store."""
    provider = IconProvider()
    for i in range(200):
        provider.for_name(f"file{i}.dll")
    assert provider.cached_extensions == 1


def test_different_extensions_cache_separately(qapp):
    provider = IconProvider()
    provider.for_name("a.dll")
    provider.for_name("b.txt")
    provider.for_name("c.exe")
    assert provider.cached_extensions == 3


def test_names_without_an_extension_are_handled(qapp):
    provider = IconProvider()
    for name in ("Makefile", ".gitignore", "trailing."):
        assert not provider.for_name(name).isNull()


def test_the_lookup_never_touches_the_disk(qapp):
    """SHGFI_USEFILEATTRIBUTES means a path that does not exist still resolves
    -- which matters, because a scan is a snapshot and the disk moves on."""
    provider = IconProvider()
    icon = provider.for_name("Z:\\nowhere\\phantom.docx")
    assert not icon.isNull()


def test_extension_matching_is_case_insensitive(qapp):
    provider = IconProvider()
    provider.for_name("A.DLL")
    provider.for_name("b.dll")
    assert provider.cached_extensions == 1
