"""Turn a raw policy registry location into something a human can read.

`Registry.pol` and RSOP give us rows like

    Software\\Policies\\Microsoft\\Windows\\CloudContent  DisableWindowsConsumerFeatures  = 1

which is exactly what gpedit *hides* from the administrator. The friendly name
("Turn off Microsoft consumer experiences"), the explain text and the tree path
under Administrative Templates all live in the ADMX/ADML pair that ships in
``C:\\Windows\\PolicyDefinitions`` -- 224 ADMX files, 3,340 ``<policy>``
elements, plus one ADML string table per file per language. This module builds
an offline reverse index over those files: (registry key, value name) -> policy.

Three things about the real files drive the design:

**Most values are not on the ``<policy>`` element.** 1,229 of the 3,340
policies have no ``valueName`` attribute at all; their values are declared by
``<elements>`` children (``<decimal>``, ``<boolean>``, ``<enum>``, ``<text>``,
``<list>``) and by ``<item key= valueName=>`` rows inside ``enabledList`` /
``disabledList`` / enum ``valueList`` -- 4,379 of those items alone. Indexing
only the policy attribute would miss most settings anyone actually sets, so we
walk the whole policy subtree for anything carrying a ``valueName``, honouring
the per-element ``key`` override (231 elements point at a different key than
their policy).

**``<list>`` has no value name.** A list writes numbered values ("1", "2", ...)
or ``valuePrefix``-numbered ones under its key, so it can only be indexed by
key. Those go in a separate key-only index consulted after an exact miss --
kept separate so an exact hit is never outranked by a fuzzy one.

**Refs cross files.** ``<parentCategory ref="windows:WindowsComponents"/>``
resolves through ``<policyNamespaces><using prefix= namespace=/>`` into another
ADMX entirely, so categories and supportedOn definitions are collected from
every file first and only then chained. Category identity is
(namespace, name), never the bare name.

Everything is lazy: nothing is parsed at import time, the first lookup builds
the index (~1 s for all 448 files) and the process keeps it. A missing
directory, a malformed ADMX or a missing ADML degrades the catalogue -- fewer
entries, never an exception -- because PolicyDefinitions is stripped on some
images.

Known gap, deliberately not papered over: AppLocker (``SrpV2``) has **no ADMX
definition** -- it is configured through its own MMC snap-in and written
straight to the registry -- so those keys return ``None`` and the caller shows
the raw key. See ``tests/test_admx_catalog.py``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Where Windows keeps the ADMX/ADML pairs. Overridable so tests can point at a
#: fixture and so a caller can read a domain Central Store instead.
DEFAULT_POLICY_DEFINITIONS_DIR = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "PolicyDefinitions"
)

PREFERRED_LANGUAGE = "en-US"

#: gpedit shows Machine policies under one root and User policies under the
#: other; the ADMX only says which class it is.
MACHINE_ROOT = "Computer Configuration/Administrative Templates"
USER_ROOT = "User Configuration/Administrative Templates"

SCOPE_MACHINE = "Machine"
SCOPE_USER = "User"
SCOPE_BOTH = "Both"

#: `$(string.SomeId)` -> SomeId
_STRING_REF = re.compile(r"^\s*\$\(string\.(.+?)\)\s*$")

#: Hive prefixes a caller may hand us; the ADMX keys are hive-relative.
_HIVE_PREFIXES = (
    "hkey_local_machine\\",
    "hkey_current_user\\",
    "hkey_users\\",
    "hklm\\",
    "hkcu\\",
    "hku\\",
    "machine\\",
    "user\\",
)

#: Registry.pol marks deletions by mangling the value name. The underlying
#: policy is the same one, so strip the marker before looking it up.
_VALUE_MARKERS = ("**del.", "**soft.", "**delvals.")

#: Ranking of how a (key, value) pair was found. A policy's own `valueName` is
#: the setting itself; an element or a list item is a knob *inside* a policy.
#: When several policies claim the same pair, the strongest claim wins.
_RANK_POLICY_VALUE = 0
_RANK_ELEMENT = 1
_RANK_LIST_ITEM = 2

#: Guards against a malformed file whose parentCategory refs form a loop.
_MAX_CATEGORY_DEPTH = 32

#: The `<?xml ... ?>` prologue. We decode the bytes ourselves and then drop it,
#: because two files that ship with Windows 11 lie in it -- see `_parse_xml`.
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)


@dataclass(frozen=True)
class PolicyInfo:
    """One Administrative Templates policy, resolved for display."""

    name: str
    """The ADMX `<policy name=>` attribute -- stable, language independent."""

    display_name: str
    """Friendly name as gpedit shows it. Falls back to `name` if the ADML is
    missing or the string id is absent."""

    explain_text: str
    """The Help/Explain paragraph. Empty string when unresolved."""

    category_path: str
    """Full gpedit path, e.g.
    `Computer Configuration/Administrative Templates/Windows Components/Cloud Content`.
    A `Both` policy is shown under the Computer root here; use
    `path_for_scope()` for the other one."""

    category_segments: Tuple[str, ...]
    """The path below Administrative Templates, root excluded."""

    scope: str
    """`Machine`, `User` or `Both` -- the ADMX `class` attribute verbatim."""

    supported_on: str
    """"Supported on" text, e.g. "At least Windows Server 2016 or Windows 10".
    Empty when the policy declares none or the ref cannot be resolved."""

    registry_key: str
    """The policy's own key, as written in the ADMX (hive-relative)."""

    value_names: Tuple[str, ...]
    """Every value name this policy writes under its key(s), in file order."""

    admx_file: str
    """Basename of the defining ADMX, e.g. `CloudContent.admx`."""

    namespace: str
    """Target namespace of that file, e.g. `Microsoft.Policies.CloudContent`."""

    def path_for_scope(self, scope: str) -> str:
        """Full gpedit path under the Computer or User root.

        `Both` policies genuinely appear in both trees; the caller usually
        knows which hive the value came from, so let it say.
        """
        root = USER_ROOT if _norm_scope(scope) == SCOPE_USER else MACHINE_ROOT
        return "/".join((root,) + self.category_segments)


@dataclass(frozen=True)
class CatalogStats:
    """What the cold build actually managed to read. Surfaced so a UI can say
    "1,203 of 224 files" instead of quietly showing fewer policies."""

    definitions_dir: str
    language: str
    """Language folder actually used -- not necessarily the preferred one."""

    admx_files_found: int
    admx_files_parsed: int
    admx_files_failed: int
    adml_files_loaded: int
    adml_files_missing: int
    policy_count: int
    pair_count: int
    """Distinct (key, value name) pairs indexed."""

    key_only_count: int
    """Distinct keys indexed for `<list>` elements, which have no value name."""

    strings_resolved: int
    strings_unresolved: int
    build_seconds: float


# --------------------------------------------------------------------------
# internal parse records
# --------------------------------------------------------------------------


@dataclass
class _RawCategory:
    display: str
    parent: Optional[Tuple[str, str]]


@dataclass
class _RawPolicy:
    name: str
    display: str
    explain: str
    scope: str
    key: str
    parent: Optional[Tuple[str, str]]
    supported: Optional[Tuple[str, str]]
    admx_file: str
    namespace: str
    #: (normalised key, normalised value name, rank, original value name)
    pairs: List[Tuple[str, str, int, str]] = field(default_factory=list)
    #: normalised keys claimed by `<list>` elements
    list_keys: List[str] = field(default_factory=list)


def _norm_key(key: str) -> str:
    """Case-fold a registry path and drop the hive, so callers may pass either
    `Software\\Policies\\...` or `HKLM\\Software\\Policies\\...`."""
    if not key:
        return ""
    text = key.strip().strip("\\").replace("/", "\\").lower()
    while "\\\\" in text:
        text = text.replace("\\\\", "\\")
    for prefix in _HIVE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip("\\")


def _norm_value(value_name: str) -> str:
    if not value_name:
        return ""
    text = value_name.strip().lower()
    for marker in _VALUE_MARKERS:
        if text.startswith(marker):
            text = text[len(marker) :]
            break
    return text


def _norm_scope(scope: Optional[str]) -> Optional[str]:
    if not scope:
        return None
    text = scope.strip().lower()
    if text in ("machine", "computer", "hklm", "localmachine"):
        return SCOPE_MACHINE
    if text in ("user", "hkcu", "currentuser"):
        return SCOPE_USER
    if text == "both":
        return SCOPE_BOTH
    return None


def _parse_xml(path: str) -> ET.Element:
    """Parse an ADMX/ADML, decoding it ourselves instead of trusting the file.

    `ET.parse` honours the `<?xml encoding=?>` declaration, and Windows 11 ships
    two files it cannot survive: `Camera.admx`/`Camera.adml` are UTF-16 (fine)
    and `Search.admx` declares `encoding='unicode'`, which is not an encoding
    name at all -- ET raises `LookupError` and, unguarded, that one file takes
    the whole catalogue down. So: sniff the BOM, decode, strip the prologue
    (ET rejects a str that still carries an encoding declaration), then parse.

    Raises the usual `ET.ParseError` / `OSError` for callers to log and skip.
    """
    with open(path, "rb") as handle:
        raw = handle.read()

    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", errors="replace")
    else:
        # utf-8-sig also strips the UTF-8 BOM these files usually carry.
        text = raw.decode("utf-8-sig", errors="replace")

    return ET.fromstring(_XML_DECL.sub("", text, count=1).lstrip("﻿").lstrip())


def _local(tag: str) -> str:
    """`{ns}policy` -> `policy`. ADMX always uses a default namespace, and
    third-party files have been seen with a different one, so never match on a
    prefix."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(parent: ET.Element, name: str) -> Optional[ET.Element]:
    return parent.find("{*}" + name)


def _iter(parent: ET.Element, name: str) -> Iterable[ET.Element]:
    return parent.iterfind("{*}" + name)


class AdmxCatalog:
    """Lazy, process-lifetime index over a PolicyDefinitions directory.

    Construct freely -- nothing touches the disk until the first lookup (or an
    explicit `ensure_loaded()`).
    """

    def __init__(
        self,
        definitions_dir: str = DEFAULT_POLICY_DEFINITIONS_DIR,
        language: str = PREFERRED_LANGUAGE,
    ) -> None:
        self.definitions_dir = definitions_dir
        self.preferred_language = language
        self._lock = threading.Lock()
        self._loaded = False
        self._stats: Optional[CatalogStats] = None
        self._by_pair: Dict[Tuple[str, str], List[Tuple[int, PolicyInfo]]] = {}
        self._by_key: Dict[str, List[Tuple[int, PolicyInfo]]] = {}
        self._policies: List[PolicyInfo] = []

    # -- public API ------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def stats(self) -> CatalogStats:
        """Build statistics; triggers the build if it has not happened yet."""
        self.ensure_loaded()
        assert self._stats is not None
        return self._stats

    def ensure_loaded(self) -> None:
        """Build the index once. Safe to call from several threads."""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:  # another thread won the race
                return
            self._build()
            self._loaded = True

    def lookup(
        self, key: str, value_name: str, scope: Optional[str] = None
    ) -> Optional[PolicyInfo]:
        """Resolve one registry location, or `None` if no ADMX defines it.

        `scope` ("Machine"/"User", or a hive name) is a hint: it filters out
        policies of the wrong class when several claim the same pair. A miss is
        normal and the caller should fall back to showing the raw key -- see
        the AppLocker note in the module docstring.
        """
        self.ensure_loaded()
        want = _norm_scope(scope)
        nkey = _norm_key(key)
        nvalue = _norm_value(value_name)

        best = self._pick(self._by_pair.get((nkey, nvalue)), want)
        if best is not None:
            return best
        # `<list>` policies write value names we cannot know in advance, so an
        # exact miss falls through to a key-only claim -- but only after.
        return self._pick(self._by_key.get(nkey), want)

    def lookup_key(self, key: str, scope: Optional[str] = None) -> List[PolicyInfo]:
        """Every policy that writes anything under `key`, best claim first."""
        self.ensure_loaded()
        nkey = _norm_key(key)
        want = _norm_scope(scope)
        seen: Dict[str, PolicyInfo] = {}
        for rank, info in sorted(self._by_key.get(nkey, [])):
            if want and info.scope not in (want, SCOPE_BOTH):
                continue
            seen.setdefault(f"{info.namespace}:{info.name}", info)
        for (pair_key, _value), entries in self._by_pair.items():
            if pair_key != nkey:
                continue
            for rank, info in sorted(entries):
                if want and info.scope not in (want, SCOPE_BOTH):
                    continue
                seen.setdefault(f"{info.namespace}:{info.name}", info)
        return list(seen.values())

    def all_policies(self) -> List[PolicyInfo]:
        self.ensure_loaded()
        return list(self._policies)

    # -- index helpers ---------------------------------------------------

    @staticmethod
    def _pick(
        entries: Optional[List[Tuple[int, PolicyInfo]]], want: Optional[str]
    ) -> Optional[PolicyInfo]:
        if not entries:
            return None
        for _rank, info in entries:  # already sorted best-first
            if want is None or info.scope in (want, SCOPE_BOTH):
                return info
        return None

    # -- building --------------------------------------------------------

    def _build(self) -> None:
        started = time.perf_counter()
        directory = self.definitions_dir
        language = ""
        admx_names: List[str] = []

        try:
            admx_names = sorted(
                n for n in os.listdir(directory) if n.lower().endswith(".admx")
            )
        except OSError as exc:
            # Stripped image, wrong edition, or a caller-supplied path that is
            # simply not there: an empty catalogue is a valid answer.
            logger.warning("ADMX directory unavailable (%s): %s", directory, exc)
            self._stats = CatalogStats(
                definitions_dir=directory,
                language="",
                admx_files_found=0,
                admx_files_parsed=0,
                admx_files_failed=0,
                adml_files_loaded=0,
                adml_files_missing=0,
                policy_count=0,
                pair_count=0,
                key_only_count=0,
                strings_resolved=0,
                strings_unresolved=0,
                build_seconds=time.perf_counter() - started,
            )
            return

        language = self._choose_language(directory)
        if not language:
            logger.warning(
                "No ADML language folder under %s; policies will show raw ids",
                directory,
            )

        categories: Dict[Tuple[str, str], _RawCategory] = {}
        supported: Dict[Tuple[str, str], str] = {}
        raw_policies: List[_RawPolicy] = []
        parsed = failed = adml_loaded = adml_missing = 0
        resolved = unresolved = 0

        for admx_name in admx_names:
            admx_path = os.path.join(directory, admx_name)
            try:
                root = _parse_xml(admx_path)
            except (ET.ParseError, OSError, ValueError) as exc:
                # One bad third-party ADMX must not cost us the other 223.
                logger.warning("Skipping unreadable ADMX %s: %s", admx_name, exc)
                failed += 1
                continue
            parsed += 1

            strings, had_adml = self._load_strings(directory, language, admx_name)
            if had_adml:
                adml_loaded += 1
            else:
                adml_missing += 1

            target_ns, prefixes = self._namespaces(root, admx_name)

            def resolve(ref: Optional[str], fallback: str = "") -> str:
                nonlocal resolved, unresolved
                if not ref:
                    return fallback
                match = _STRING_REF.match(ref)
                if not match:
                    return ref  # literal text, allowed by the schema
                text = strings.get(match.group(1))
                if text is None:
                    logger.debug(
                        "%s: unresolved string id %s", admx_name, match.group(1)
                    )
                    unresolved += 1
                    return fallback
                resolved += 1
                return text

            self._collect_categories(
                root, target_ns, prefixes, resolve, categories, admx_name
            )
            self._collect_supported(root, target_ns, prefixes, resolve, supported)
            self._collect_policies(
                root,
                target_ns,
                prefixes,
                resolve,
                raw_policies,
                admx_name,
            )

        path_cache: Dict[Tuple[str, str], Tuple[str, ...]] = {}
        for raw in raw_policies:
            segments = self._category_path(raw.parent, categories, path_cache)
            info = PolicyInfo(
                name=raw.name,
                display_name=raw.display or raw.name,
                explain_text=raw.explain,
                category_path="/".join(
                    ((USER_ROOT if raw.scope == SCOPE_USER else MACHINE_ROOT),)
                    + segments
                ),
                category_segments=segments,
                scope=raw.scope,
                supported_on=supported.get(raw.supported, "") if raw.supported else "",
                registry_key=raw.key,
                value_names=tuple(dict.fromkeys(v for _k, _n, _r, v in raw.pairs)),
                admx_file=raw.admx_file,
                namespace=raw.namespace,
            )
            self._policies.append(info)
            for nkey, nvalue, rank, _orig in raw.pairs:
                self._by_pair.setdefault((nkey, nvalue), []).append((rank, info))
            for nkey in raw.list_keys:
                self._by_key.setdefault(nkey, []).append((_RANK_LIST_ITEM, info))

        # Sort once so every lookup can take the first entry it accepts.
        for entries in self._by_pair.values():
            entries.sort(key=lambda item: (item[0], item[1].name))
        for entries in self._by_key.values():
            entries.sort(key=lambda item: (item[0], item[1].name))

        self._stats = CatalogStats(
            definitions_dir=directory,
            language=language,
            admx_files_found=len(admx_names),
            admx_files_parsed=parsed,
            admx_files_failed=failed,
            adml_files_loaded=adml_loaded,
            adml_files_missing=adml_missing,
            policy_count=len(self._policies),
            pair_count=len(self._by_pair),
            key_only_count=len(self._by_key),
            strings_resolved=resolved,
            strings_unresolved=unresolved,
            build_seconds=time.perf_counter() - started,
        )
        logger.debug(
            "ADMX catalogue: %d policies, %d pairs from %s in %.2fs",
            self._stats.policy_count,
            self._stats.pair_count,
            directory,
            self._stats.build_seconds,
        )

    def _choose_language(self, directory: str) -> str:
        """Prefer en-US; otherwise take whatever language folder is present.

        Non-English images ship only their own ADML, and a German explain text
        beats no explain text.
        """
        candidates: List[str] = []
        try:
            for entry in sorted(os.listdir(directory)):
                full = os.path.join(directory, entry)
                if not os.path.isdir(full):
                    continue
                try:
                    has_adml = any(
                        n.lower().endswith(".adml") for n in os.listdir(full)
                    )
                except OSError as exc:
                    logger.debug("Cannot list language folder %s: %s", full, exc)
                    continue
                if has_adml:
                    candidates.append(entry)
        except OSError as exc:
            logger.warning("Cannot list %s for language folders: %s", directory, exc)
            return ""
        for entry in candidates:
            if entry.lower() == self.preferred_language.lower():
                return entry
        return candidates[0] if candidates else ""

    @staticmethod
    def _load_strings(
        directory: str, language: str, admx_name: str
    ) -> Tuple[Dict[str, str], bool]:
        """Read the ADML string table beside an ADMX. Missing is normal."""
        if not language:
            return {}, False
        adml_path = os.path.join(
            directory, language, admx_name[: -len(".admx")] + ".adml"
        )
        try:
            root = _parse_xml(adml_path)
        except FileNotFoundError:
            logger.debug("No ADML for %s in %s", admx_name, language)
            return {}, False
        except (ET.ParseError, OSError, ValueError) as exc:
            logger.warning("Skipping unreadable ADML %s: %s", adml_path, exc)
            return {}, False

        table: Dict[str, str] = {}
        for node in root.iter():
            if _local(node.tag) != "string":
                continue
            ident = node.get("id")
            if ident:
                # ADML wraps long help text across lines; keep it as authored.
                table[ident] = (node.text or "").strip()
        return table, True

    @staticmethod
    def _namespaces(root: ET.Element, admx_name: str) -> Tuple[str, Dict[str, str]]:
        """Return (target namespace, prefix -> namespace) for one file."""
        target_ns = ""
        prefixes: Dict[str, str] = {}
        block = _find(root, "policyNamespaces")
        if block is None:
            logger.debug("%s: no <policyNamespaces>", admx_name)
            return admx_name, prefixes
        target = _find(block, "target")
        if target is not None:
            target_ns = target.get("namespace") or ""
            prefix = target.get("prefix")
            if prefix:
                prefixes[prefix] = target_ns
        for using in _iter(block, "using"):
            prefix = using.get("prefix")
            namespace = using.get("namespace")
            if prefix and namespace:
                prefixes[prefix] = namespace
        return target_ns or admx_name, prefixes

    @staticmethod
    def _qualify(
        ref: Optional[str], target_ns: str, prefixes: Dict[str, str]
    ) -> Optional[Tuple[str, str]]:
        """`windows:WindowsComponents` -> (`Microsoft.Policies.Windows`,
        `WindowsComponents`); a bare name belongs to this file's namespace."""
        if not ref:
            return None
        if ":" in ref:
            prefix, _sep, name = ref.partition(":")
            return prefixes.get(prefix, prefix), name
        return target_ns, ref

    @classmethod
    def _collect_categories(
        cls,
        root: ET.Element,
        target_ns: str,
        prefixes: Dict[str, str],
        resolve,
        out: Dict[Tuple[str, str], _RawCategory],
        admx_name: str,
    ) -> None:
        block = _find(root, "categories")
        if block is None:
            return
        for node in _iter(block, "category"):
            name = node.get("name")
            if not name:
                logger.debug("%s: <category> with no name", admx_name)
                continue
            parent_node = _find(node, "parentCategory")
            parent = (
                cls._qualify(parent_node.get("ref"), target_ns, prefixes)
                if parent_node is not None
                else None
            )
            out[(target_ns, name)] = _RawCategory(
                display=resolve(node.get("displayName"), name), parent=parent
            )

    @classmethod
    def _collect_supported(
        cls,
        root: ET.Element,
        target_ns: str,
        prefixes: Dict[str, str],
        resolve,
        out: Dict[Tuple[str, str], str],
    ) -> None:
        block = _find(root, "supportedOn")
        if block is None:
            return
        definitions = _find(block, "definitions")
        if definitions is None:
            return
        for node in _iter(definitions, "definition"):
            name = node.get("name")
            if not name:
                continue
            out[(target_ns, name)] = resolve(node.get("displayName"), name)

    @classmethod
    def _collect_policies(
        cls,
        root: ET.Element,
        target_ns: str,
        prefixes: Dict[str, str],
        resolve,
        out: List[_RawPolicy],
        admx_name: str,
    ) -> None:
        block = _find(root, "policies")
        if block is None:
            return
        for node in _iter(block, "policy"):
            name = node.get("name")
            key = node.get("key") or ""
            if not name:
                logger.debug("%s: <policy> with no name", admx_name)
                continue

            parent_node = _find(node, "parentCategory")
            supported_node = _find(node, "supportedOn")
            raw = _RawPolicy(
                name=name,
                display=resolve(node.get("displayName"), name),
                explain=resolve(node.get("explainText"), ""),
                scope=node.get("class") or SCOPE_BOTH,
                key=key,
                parent=(
                    cls._qualify(parent_node.get("ref"), target_ns, prefixes)
                    if parent_node is not None
                    else None
                ),
                supported=(
                    cls._qualify(supported_node.get("ref"), target_ns, prefixes)
                    if supported_node is not None
                    else None
                ),
                admx_file=admx_name,
                namespace=target_ns,
            )

            base_key = _norm_key(key)
            # One policy can claim the same (key, value) through several paths --
            # inetres.admx's zone templates list the same value once per zone
            # item -- and five identical index entries help nobody.
            seen_pairs = set()

            def claim(nkey: str, value: str, rank: int) -> None:
                nvalue = _norm_value(value)
                if (nkey, nvalue) in seen_pairs:
                    return
                seen_pairs.add((nkey, nvalue))
                raw.pairs.append((nkey, nvalue, rank, value))

            own_value = node.get("valueName")
            if own_value:
                claim(base_key, own_value, _RANK_POLICY_VALUE)

            # Walk the whole subtree rather than just <elements>: enabledList,
            # disabledList and enum <valueList> items write real registry
            # values too, and they carry the same key/valueName attributes.
            for child in node.iter():
                if child is node:
                    continue
                tag = _local(child.tag)
                child_key = _norm_key(child.get("key") or "") or base_key
                if tag == "list":
                    # No value name exists: a list writes "1", "2", ... (or
                    # valuePrefix + N) under its key. Key-only claim.
                    if child_key and child_key not in raw.list_keys:
                        raw.list_keys.append(child_key)
                    continue
                value = child.get("valueName")
                if not value:
                    continue
                claim(child_key, value, _RANK_ELEMENT if tag != "item" else _RANK_LIST_ITEM)

            if not raw.pairs and not raw.list_keys and not base_key:
                logger.debug("%s: policy %s declares no registry location", admx_name, name)
            out.append(raw)

    @staticmethod
    def _category_path(
        start: Optional[Tuple[str, str]],
        categories: Dict[Tuple[str, str], _RawCategory],
        cache: Dict[Tuple[str, str], Tuple[str, ...]],
    ) -> Tuple[str, ...]:
        """Chain parentCategory refs up to the root, root-first."""
        if start is None:
            return ()
        if start in cache:
            return cache[start]

        segments: List[str] = []
        seen = set()
        node = start
        depth = 0
        while node is not None and depth < _MAX_CATEGORY_DEPTH:
            if node in seen:
                logger.warning("Category cycle at %s:%s", node[0], node[1])
                break
            seen.add(node)
            record = categories.get(node)
            if record is None:
                # Ref into an ADMX this machine does not have. Show the raw
                # name rather than dropping a level out of the path.
                logger.debug("Unknown category ref %s:%s", node[0], node[1])
                segments.append(node[1])
                break
            segments.append(record.display)
            node = record.parent
            depth += 1

        path = tuple(reversed(segments))
        cache[start] = path
        return path


# --------------------------------------------------------------------------
# process-wide cache
# --------------------------------------------------------------------------

_catalogs: Dict[Tuple[str, str], AdmxCatalog] = {}
_catalogs_lock = threading.Lock()


def get_catalog(
    definitions_dir: str = DEFAULT_POLICY_DEFINITIONS_DIR,
    language: str = PREFERRED_LANGUAGE,
) -> AdmxCatalog:
    """The shared catalogue for a directory. Still lazy -- returning it parses
    nothing; the first lookup does, once, for the life of the process."""
    cache_key = (os.path.normcase(os.path.abspath(definitions_dir)), language)
    with _catalogs_lock:
        catalog = _catalogs.get(cache_key)
        if catalog is None:
            catalog = AdmxCatalog(definitions_dir, language)
            _catalogs[cache_key] = catalog
        return catalog


def lookup_policy(
    key: str,
    value_name: str,
    scope: Optional[str] = None,
    definitions_dir: str = DEFAULT_POLICY_DEFINITIONS_DIR,
    language: str = PREFERRED_LANGUAGE,
) -> Optional[PolicyInfo]:
    """Convenience wrapper over the shared catalogue.

    Returns `None` when no ADMX on this machine defines the location -- the
    caller should then display the raw key/value.
    """
    return get_catalog(definitions_dir, language).lookup(key, value_name, scope)


def clear_cache() -> None:
    """Drop the shared catalogues (tests, or after a Central Store change)."""
    with _catalogs_lock:
        _catalogs.clear()
