"""User-defined highlight rules -- CMTrace's Highlight, kept Qt-free.

A rule is the one thing allowed to override severity on a row's background:
the user typed it, so it outranks a colour the log chose for itself. The
Component column is unaffected either way; its tint owns that cell.

Rules are matched in order and the first match wins, so the order in the
editor is meaningful and visible rather than incidental.
"""
import logging
import re
from dataclasses import asdict, dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

#: Global, not per file: "highlight my machine name" should apply to every
#: log that is opened, which is what the user asked for.
CONFIG_KEY = "log_viewer.highlight_rules"


@dataclass(frozen=True)
class HighlightRule:
    pattern: str
    colour: str                 # "#RRGGBB", chosen by the user
    regex: bool = False
    enabled: bool = True


def _haystack(entry) -> str:
    """The row as the user sees it, which is what LogModel._matches uses.

    A rule that could only see the message could not target a component,
    and "colour every CSI row" is one of the obvious things to want.
    """
    return f"{entry.message} {entry.level} {entry.source}"


def matching_rule(rules, entry) -> Optional[HighlightRule]:
    text = _haystack(entry)
    lowered = text.lower()
    for rule in rules or ():
        if not rule.enabled or not rule.pattern:
            continue
        if rule.regex:
            try:
                if re.search(rule.pattern, text, re.IGNORECASE):
                    return rule
            except re.error:
                # A half-typed pattern is a typo, not a failure. The editor
                # flags it; matching just declines.
                continue
        elif rule.pattern.lower() in lowered:
            return rule
    return None


def load_rules(config) -> List[HighlightRule]:
    stored = config.get(CONFIG_KEY, []) or []
    rules = []
    for item in stored:
        try:
            rules.append(HighlightRule(
                pattern=str(item["pattern"]),
                colour=str(item["colour"]),
                regex=bool(item.get("regex", False)),
                enabled=bool(item.get("enabled", True)),
            ))
        except (TypeError, KeyError, ValueError):
            # One hand-edited entry must not cost the user every rule.
            logger.warning("Skipping an unreadable highlight rule: %r", item)
    return rules


def save_rules(config, rules) -> None:
    config.set(CONFIG_KEY, [asdict(rule) for rule in rules])
    config.save()
