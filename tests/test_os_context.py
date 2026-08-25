"""OSContext decides whether a tweak gets a real verdict or "Not Applicable",
so its matching rules need to be exact — an over-eager `applies_to` silently
hides working tweaks, and a lax one shows tweaks that cannot do anything."""
import pytest

from modules.tweaks.os_context import (
    OSContext, get_os_context, reset_os_context, resolve_build,
)


@pytest.fixture
def ctx():
    """A context with the machine facts pinned, so these tests say the same
    thing on a Win10 CI box as on a Win11 desktop."""
    c = OSContext.__new__(OSContext)
    c.build = 26100
    c.ubr = 3775
    c.display_version = "24H2"
    c.edition_id = "Professional"
    c.product_name = "Windows 11 Pro"
    c.install_type = "Client"
    c.arch = "AMD64"
    c._service_cache = {}
    c._task_cache = {}
    c._appx_names = None
    c._appx_failed = False
    return c


# -- build aliases ---------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [
    (22631, 22631),
    ("22631", 22631),
    ("23H2", 22631),
    ("24h2", 26100),
    ("win11", 22000),
    ("WIN11_24H2", 26100),
    (None, None),
    ("", None),
])
def test_resolve_build(spec, expected):
    assert resolve_build(spec) == expected


def test_unknown_alias_is_no_constraint_not_a_never_match():
    """A typo in a definition file must not silently hide a working tweak."""
    assert resolve_build("nonsense") is None


# -- applies_to ------------------------------------------------------------

def test_no_applies_to_block_is_always_applicable(ctx):
    assert ctx.evaluate(None).applicable
    assert ctx.evaluate({}).applicable


def test_min_build_below_current_passes(ctx):
    assert ctx.evaluate({"min_build": 22000}).applicable


def test_min_build_above_current_fails_with_both_numbers(ctx):
    verdict = ctx.evaluate({"min_build": 27000})
    assert not verdict.applicable
    assert "27000" in verdict.reason and "26100" in verdict.reason


def test_max_build_gate(ctx):
    assert ctx.evaluate({"max_build": 26100}).applicable, "max_build is inclusive"
    assert not ctx.evaluate({"max_build": 19045}).applicable


def test_os_gate(ctx):
    assert ctx.evaluate({"os": "win11"}).applicable
    assert not ctx.evaluate({"os": "win10"}).applicable
    assert ctx.evaluate({"os": "any"}).applicable


def test_edition_allowlist(ctx):
    assert ctx.evaluate({"editions": ["Professional", "Enterprise"]}).applicable
    verdict = ctx.evaluate({"editions": ["Enterprise"]})
    assert not verdict.applicable
    assert "Professional" in verdict.reason


def test_edition_denylist(ctx):
    assert not ctx.evaluate({"not_editions": ["Professional"]}).applicable
    assert ctx.evaluate({"not_editions": ["Core"]}).applicable


def test_arch_gate(ctx):
    assert ctx.evaluate({"arch": ["AMD64"]}).applicable
    verdict = ctx.evaluate({"arch": ["ARM64"]})
    assert not verdict.applicable
    assert "AMD64" in verdict.reason


def test_requires_gpedit_passes_on_pro(ctx):
    assert ctx.evaluate({"requires_gpedit": True}).applicable


def test_requires_gpedit_fails_on_home(ctx):
    """Home writes the policy value happily and then ignores it. Reporting
    "Not Applied" forever would be worse than saying it does not apply."""
    ctx.edition_id = "Core"
    verdict = ctx.evaluate({"requires_gpedit": True})
    assert not verdict.applicable
    assert "Group Policy" in verdict.reason


def test_client_only_gate(ctx):
    assert ctx.evaluate({"client_only": True}).applicable
    ctx.install_type = "Server"
    assert not ctx.evaluate({"client_only": True}).applicable


def test_conditions_are_anded(ctx):
    assert not ctx.evaluate({"min_build": 22000, "arch": ["ARM64"]}).applicable


# -- derived facts ---------------------------------------------------------

def test_win11_boundary_is_build_22000(ctx):
    ctx.build = 22000
    assert ctx.is_win11 and not ctx.is_win10
    ctx.build = 19045
    assert ctx.is_win10 and not ctx.is_win11


def test_home_edition_detection_is_case_insensitive(ctx):
    ctx.edition_id = "CoreSingleLanguage"
    assert ctx.is_home_edition
    ctx.edition_id = "Professional"
    assert not ctx.is_home_edition


def test_friendly_name_carries_what_the_verdicts_are_judged_against(ctx):
    name = ctx.friendly_name
    assert "Windows 11" in name and "24H2" in name
    assert "26100" in name and "AMD64" in name


# -- appx cache ------------------------------------------------------------

def test_appx_lookup_supports_wildcards(ctx):
    ctx._appx_names = frozenset({"microsoft.bingnews", "microsoft.zunevideo"})
    assert ctx.appx_installed("Microsoft.BingNews") is True
    assert ctx.appx_installed("Microsoft.Bing*") is True
    assert ctx.appx_installed("Microsoft.Todos") is False


def test_failed_appx_enumeration_is_none_not_empty(ctx):
    """None means "we could not look". Returning False would report every app
    as already removed."""
    ctx._appx_failed = True
    assert ctx.appx_installed("Microsoft.BingNews") is None


def test_invalidate_appx_cache_clears_the_failure_flag(ctx):
    ctx._appx_failed = True
    ctx._appx_names = frozenset({"a"})
    ctx.invalidate_appx_cache()
    assert ctx._appx_names is None and ctx._appx_failed is False


# -- singleton -------------------------------------------------------------

def test_get_os_context_is_cached():
    reset_os_context()
    try:
        assert get_os_context() is get_os_context()
    finally:
        reset_os_context()
