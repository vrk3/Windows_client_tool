"""User-defined highlight rules: the one thing allowed to override severity
on a row's background, because the user typed it deliberately."""
from datetime import datetime

from core.types import LogEntry
from modules.log_viewer.highlight import (CONFIG_KEY, HighlightRule,
                                          load_rules, matching_rule,
                                          save_rules)


class _StubConfig:
    """ConfigManager's get/set/save, and nothing else."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = False

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.saved = True


def _entry(message, level="Info", source="CBS"):
    return LogEntry(timestamp=datetime(2026, 8, 30, 12, 0, 0), source=source,
                    level=level, message=message, raw={})


def test_the_first_matching_rule_wins():
    rules = [HighlightRule("turbostack", "#00ff00"),
             HighlightRule("version", "#ff0000")]
    assert matching_rule(rules, _entry("TurboStack version 10")).colour \
        == "#00ff00"


def test_matching_is_case_insensitive():
    rules = [HighlightRule("TURBOSTACK", "#00ff00")]
    assert matching_rule(rules, _entry("turbostack loaded")) is not None


def test_a_disabled_rule_is_skipped_without_being_forgotten():
    rules = [HighlightRule("boom", "#00ff00", enabled=False),
             HighlightRule("boom", "#ff0000")]
    assert matching_rule(rules, _entry("boom")).colour == "#ff0000"


def test_a_rule_can_target_a_component_or_a_level():
    """The haystack is the row as the user sees it, matching the filter."""
    rules = [HighlightRule("CSI", "#00ff00")]
    assert matching_rule(rules, _entry("nothing here", source="CSI"))
    rules = [HighlightRule("Warning", "#00ff00")]
    assert matching_rule(rules, _entry("nothing", level="Warning"))


def test_an_invalid_regex_matches_nothing_and_does_not_raise():
    """A half-typed pattern is a typo, not a failure -- the same rule
    LogSearchProvider.search already follows."""
    rules = [HighlightRule("[unclosed", "#00ff00", regex=True)]
    assert matching_rule(rules, _entry("[unclosed")) is None


def test_a_regex_rule_matches_as_a_regex():
    rules = [HighlightRule(r"HRESULT = 0x8007[0-9a-f]{4}", "#00ff00",
                           regex=True)]
    assert matching_rule(rules, _entry("failed [HRESULT = 0x80070005]"))


def test_no_rules_means_no_match():
    assert matching_rule([], _entry("anything")) is None


def test_rules_round_trip_through_the_config():
    config = _StubConfig()
    rules = [HighlightRule("boom", "#ff0000", regex=True, enabled=False)]
    save_rules(config, rules)
    assert config.saved
    assert load_rules(config) == rules


def test_a_corrupt_rule_does_not_cost_the_user_the_others():
    config = _StubConfig({CONFIG_KEY: [
        {"pattern": "good", "colour": "#00ff00"},
        {"nonsense": True},
        "not even a dict",
    ]})
    assert [rule.pattern for rule in load_rules(config)] == ["good"]


def test_no_stored_rules_is_an_empty_list_not_a_crash():
    assert load_rules(_StubConfig()) == []


def test_a_malformed_colour_loses_only_its_own_rule():
    """readable_text_on raises on anything that is not "#" + six hex digits,
    and that exception reaches a Qt virtual where it is fatal -- so a
    hand-edited config with a bad colour must be rejected here, at load
    time, rather than crashing later when the row is painted."""
    config = _StubConfig({CONFIG_KEY: [
        {"pattern": "good", "colour": "#00ff00"},
        {"pattern": "bad", "colour": "red"},
        {"pattern": "also bad", "colour": "#12345g"},
    ]})
    assert [rule.pattern for rule in load_rules(config)] == ["good"]
