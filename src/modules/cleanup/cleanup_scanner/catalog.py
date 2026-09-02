"""Scanner definitions as data, with one engine over them.

538 `scan_*` functions across eight files — 440 KB, roughly a tenth of the
whole codebase — were the same three lines: expand some environment
variables into paths, hand each to `_make_item`, sum the sizes. A census of
them found 430 that were a plain path list and 79 more that differed only
by a glob; 95% of the file weight was the boilerplate around the 5% that
was actually knowledge.

The Tweaks module already proved the shape for a comparable body of
knowledge: ~700 entries in JSON, one engine, and one structural test that
can ask every entry a question at once. `tests/test_cleanup_catalog.py` is
the counterpart here, and it can now assert things no review reliably
could — that every scanner declares a safety level, that no two share a
label, that none hardcodes a drive letter.

**Paths are written with environment variables**, never drive letters:
`%LOCALAPPDATA%`, `%APPDATA%`, `%windir%`, `%ProgramData%`. A machine with
Windows on D: is not hypothetical, and hardcoding C: is how the old
scanners quietly found nothing there (audit #16). An unresolved variable
means the scanner is skipped, not that it matches the literal `%FOO%`.

Scanners that are genuinely more than a path list — the two that read the
registry or shell out, and the twenty that walk a tree with their own
rules — stay as Python functions. This engine is for the 95%, not a
framework to force the rest through.
"""
from __future__ import annotations

import glob as globlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from modules.cleanup.cleanup_scanner._common import ScanResult, _make_item

logger = logging.getLogger(__name__)

_DEFINITIONS = Path(__file__).parent / "definitions"

#: The three levels the cleanup UI colours and the "Clean All Safe" button
#: filters on. A scanner with no safety level would be silently swept by it.
SAFETY_LEVELS = ("safe", "caution", "danger")


@dataclass(frozen=True)
class ScannerSpec:
    """One thing the cleanup scanner knows how to measure and remove."""

    id: str
    label: str
    paths: List[str]
    category: str = ""
    safety: str = "safe"
    #: Days a path must be untouched before it counts. The tab's own age
    #: slider overrides this; it is a floor for scanners where recent data
    #: is still in use (a browser profile mid-session, say).
    min_age_default: int = 0
    description: str = ""
    #: Explicitly not scanned on this machine, with the reason. Kept as data
    #: rather than deleted so the knowledge does not have to be rediscovered.
    disabled_reason: str = ""

    def __post_init__(self) -> None:
        if self.safety not in SAFETY_LEVELS:
            raise ValueError(f"{self.id}: safety {self.safety!r} not one of {SAFETY_LEVELS}")
        if not self.paths:
            raise ValueError(f"{self.id}: a scanner with no paths measures nothing")


_catalog: Optional[Dict[str, ScannerSpec]] = None


def load_catalog(force: bool = False) -> Dict[str, ScannerSpec]:
    """Every scanner, keyed by id. Parsed once per process.

    `force` exists for tests that write a definitions file; nothing in the
    app should need it.
    """
    global _catalog
    if _catalog is None or force:
        specs: Dict[str, ScannerSpec] = {}
        for path in sorted(_DEFINITIONS.glob("*.json")):
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            for row in payload["scanners"]:
                spec = ScannerSpec(category=payload.get("category", path.stem), **row)
                if spec.id in specs:
                    raise ValueError(
                        f"duplicate scanner id {spec.id!r} in {path.name} — "
                        f"already defined in {specs[spec.id].category}")
                specs[spec.id] = spec
        _catalog = specs
    return _catalog


def expand(raw: str) -> Optional[str]:
    """Resolve `%VAR%` references, or None if any of them is unset.

    None rather than the half-expanded string: `%LOCALAPPDATA%\\Foo` with
    LOCALAPPDATA unset expands to the literal `%LOCALAPPDATA%\\Foo`, which
    os.path.exists cheerfully answers False for — so the scanner silently
    finds nothing rather than saying it could not look.
    """
    expanded = os.path.expandvars(raw)
    if "%" in expanded:
        return None
    return expanded


def targets_of(spec: ScannerSpec) -> List[str]:
    """The concrete paths `spec` points at on this machine, globs resolved."""
    found: List[str] = []
    for raw in spec.paths:
        expanded = expand(raw)
        if expanded is None:
            logger.debug("%s: unresolved variable in %r, skipping", spec.id, raw)
            continue
        if any(ch in expanded for ch in "*?["):
            found.extend(sorted(globlib.glob(expanded)))
        else:
            found.append(expanded)
    return found


def run_spec(spec: ScannerSpec, min_age_days: int = 0) -> ScanResult:
    """Measure everything `spec` points at.

    A path that is not there is not an error — most of these belong to
    optional software, and "Steam's shader cache is absent" is the normal
    answer on a machine without Steam.
    """
    result = ScanResult()
    if spec.disabled_reason:
        return result

    age = min_age_days if min_age_days else spec.min_age_default
    for target in targets_of(spec):
        item = _make_item(target, safety=spec.safety, min_age_days=age)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scanner_for(spec_id: str) -> Callable[..., ScanResult]:
    """A callable with the old `scan_x(min_age_days=0)` signature.

    The cleanup tabs pass `{function: label}` dicts around, so the generated
    scanners have to be indistinguishable from the hand-written ones they
    replace.
    """
    spec = load_catalog()[spec_id]

    def _scan(min_age_days: int = 0) -> ScanResult:
        return run_spec(spec, min_age_days)

    _scan.__name__ = f"scan_{spec_id}"
    _scan.__qualname__ = _scan.__name__
    _scan.__doc__ = spec.description or spec.label
    _scan.spec = spec  # type: ignore[attr-defined]
    return _scan


def all_scanners() -> Dict[str, Callable[..., ScanResult]]:
    """`{"scan_<id>": callable}` for every spec in the catalog."""
    return {f"scan_{spec_id}": scanner_for(spec_id) for spec_id in load_catalog()}
