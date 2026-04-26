# Cleanup & Disk Module — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken browser scanner in the Cleanup module so it correctly detects and cleans all browser caches (Chrome, Edge, Firefox, etc.) across all profiles. The scanner must handle running browsers, permission errors, and all modern cache locations gracefully.

**Architecture:** New `BrowserScanner2` class added to `browser_scanner.py` alongside existing `EnhancedBrowserScanner`. `CleanupModule` wires `_BrowserCleanupTab` and `_OverviewTab` to use the new scanner. No changes to the tab UI — only the scanner logic underneath.

**Tech Stack:** Python 3.12, PyQt6, psutil, shutil

---

## File Changes

| File | Action |
|---|---|
| `src/modules/cleanup/browser_scanner.py` | Add `BrowserScanner2` class (phases 1) |
| `src/modules/cleanup/tabs/_browser_tab.py` | Wire to `BrowserScanner2`, add running browser warning, show locked items |
| `src/modules/cleanup/tabs/_overview_tab.py` | Wire browser group to `BrowserScanner2.detect_browsers()` |
| `src/modules/cleanup/cleanup_module.py` | No code changes needed |

---

## Task 1: Add BrowserScanner2 class to browser_scanner.py

**Files:**
- Modify: `src/modules/cleanup/browser_scanner.py`

- [ ] **Step 1: Add dataclasses and constants at top of file**

After existing `@dataclass` definitions, add new ones:

```python
@dataclass
class CacheEntry:
    """A single cache directory within a browser profile."""
    label: str           # e.g. "Code Cache", "Cache2"
    path: Path
    size_bytes: int = 0
    exists: bool = False
    locked: bool = False  # True if browser running or access denied

    def __post_init__(self):
        if self.size_bytes < 0:
            self.size_bytes = 0


@dataclass
class BrowserProfile:
    """A single browser profile (e.g. Default, Profile 2)."""
    name: str
    path: Path
    caches: List[CacheEntry] = None
    error: Optional[str] = None

    def __post_init__(self):
        self.caches = self.caches or []
        self._total: int = 0

    @property
    def total_bytes(self) -> int:
        if self._total:
            return self._total
        self._total = sum(c.size_bytes for c in self.caches)
        return self._total


@dataclass
class BrowserScanResult:
    """Result for one browser engine (Chrome, Edge, Firefox, etc.)."""
    name: str
    engine: str          # "chromium" | "firefox"
    is_running: bool = False
    profiles: List[BrowserProfile] = None
    error: Optional[str] = None

    def __post_init__(self):
        self.profiles = self.profiles or []

    @property
    def total_bytes(self) -> int:
        return sum(p.total_bytes for p in self.profiles)

    @property
    def total_caches(self) -> int:
        return sum(len(p.caches) for p in self.profiles)

    @property
    def locked_count(self) -> int:
        return sum(1 for p in self.profiles for c in p.caches if c.locked)
```

- [ ] **Step 2: Add all browser definitions after existing definitions**

After `FIREFOX_BROWSERS`, add:

```python
# Browser executable mappings (consolidated)
BROWSER_EXES = {
    "Brave":      "brave.exe",
    "Chrome":     "chrome.exe",
    "Edge":       "msedge.exe",
    "Vivaldi":    "vivaldi.exe",
    "Thorium":    "thorium.exe",
    "Chromium":   "chrome.exe",
    "Yandex":     "browser.exe",
    "Opera":      "opera.exe",
    "Opera GX":   "opera.exe",
    "Firefox":    "firefox.exe",
    "LibreWolf":  "librewolf.exe",
    "Waterfox":   "waterfox.exe",
    "Pale Moon":  "palemoon.exe",
}

# All modern cache subdirectories for Chromium-based browsers
CHROMIUM_CACHE_SUBDIRS = {
    "Cache":                     "HTTP Cache",
    "Cache2":                    "HTTP Cache v2",
    "Code Cache":                "Compiled JS/WASM",
    "GPUCache":                  "GPU Shader Cache",
    "Media Cache":               "Media Cache",
    "blob_storage":              "Blob Storage",
    "ShaderCache":               "Shader Cache",
    "GrShaderCache":             "General Shader Cache",
    "DawnCache":                 "Dawn WebGPU Cache",
    "Extension Cache":           "Extension Cache",
    "Local App Settings":        "Local App Settings",
    "Local Storage":             "Local Storage",
    "Sessions":                  "Tab Sessions",
    "Tabs":                      "Tab Data",
    "Web Application History":   "Web App History",
    r"Crashpad\reports":         "Crash Reports",
    r"Crashpad\pending":         "Pending Crash Reports",
    r"GrShaderCache\GPUCache":  "GPU Cache (sub)",
    r"ShaderCache\GPUCache":     "GPU Cache (sub)",
}

# Firefox cache subdirectories
FIREFOX_CACHE_SUBDIRS = {
    "cache2":               "HTTP Cache",
    "cache":                "HTTP Cache (legacy)",
    "offlineCache":         "Offline Cache",
    "thumbnails":           "Page Thumbnails",
    "startupCache":         "Startup Cache",
    r"crashes\submitted":   "Submitted Crashes",
    r"crashes\pending":     "Pending Crashes",
    "minidumps":            "Minidumps",
}
```

- [ ] **Step 3: Add BrowserScanner2 class before the module-level convenience functions**

Add the class definition:

```python
class BrowserScanner2:
    """
    Robust browser cache scanner — enumerates all profiles and all modern
    cache locations per browser engine.

    Usage:
        scanner = BrowserScanner2()
        results = scanner.scan()  # List[BrowserScanResult]
    """

    def _is_browser_running(self, exe_name: str) -> bool:
        """Check if a browser process is running."""
        try:
            import psutil
            exe_lower = exe_name.lower()
            for p in psutil.process_iter(["name"]):
                try:
                    if p.info["name"] and p.info["name"].lower() == exe_lower:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
        return False

    def _find_chromium_profiles(self, user_data: Path) -> List[Path]:
        """Find all Chromium-based browser profiles with maximum coverage."""
        profiles = []
        seen = set()

        # 1. Local State info_cache — canonical source
        local_state = user_data / "Local State"
        if local_state.is_file():
            try:
                with open(local_state, encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                cache = data.get("profile", {}).get("info_cache", {})
                for name in cache:
                    p = user_data / name
                    if p.is_dir() and p not in seen:
                        profiles.append(p)
                        seen.add(p)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                logger.debug(f"Local State parse failed for {user_data}: {e}")

        # 2. Directory scan for profile folders
        for entry in os.scandir(user_data):
            if not entry.is_dir(follow_symlinks=False):
                continue
            entry_path = Path(entry.path)
            if entry_path in seen:
                continue
            name_lower = entry.name.lower()
            # Matches: "Default", "Profile 1", "Profile 2", etc.
            if name_lower == "default" or name_lower.startswith("profile"):
                profiles.append(entry_path)
                seen.add(entry_path)

        return profiles

    def _find_firefox_profiles(self, profiles_dir: Path) -> List[Path]:
        """Find all Firefox profiles from Profiles folder."""
        profiles = []
        if not profiles_dir.is_dir():
            return profiles
        for entry in os.scandir(profiles_dir):
            if entry.is_dir(follow_symlinks=False):
                profiles.append(Path(entry.path))
        profiles.sort(key=lambda p: p.name)
        return profiles

    def _scan_cache_path(self, cache_path: Path, label: str) -> CacheEntry:
        """Scan a single cache path and return a CacheEntry."""
        entry = CacheEntry(label=label, path=cache_path)
        if not cache_path.exists():
            entry.exists = False
            return entry
        entry.exists = True

        # Check if accessible
        try:
            entry.size_bytes = self._dir_size(cache_path)
        except PermissionError:
            entry.locked = True
            entry.size_bytes = 0
        except OSError:
            entry.locked = True
            entry.size_bytes = 0

        return entry

    def _dir_size(self, path: Path, max_depth: int = 1) -> int:
        """Calculate directory size with depth limit to avoid deep traversals."""
        total = 0
        try:
            for entry in path.iterdir():
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        # One level deeper
                        for sub in entry.iterdir():
                            try:
                                if sub.is_file(follow_symlinks=False):
                                    total += sub.stat().st_size
                            except OSError:
                                pass
                except OSError:
                    pass
        except OSError:
            pass
        return total

    def scan_chromium_browser(
        self,
        name: str,
        user_data: Path,
        use_appdata: bool = False,
    ) -> BrowserScanResult:
        """Scan a Chromium-based browser (Chrome, Edge, Brave, etc.)."""
        exe = BROWSER_EXES.get(name, "")
        result = BrowserScanResult(name=name, engine="chromium")
        result.is_running = self._is_browser_running(exe)

        if not user_data.is_dir():
            result.error = f"User Data folder not found: {user_data}"
            return result

        for prof_path in self._find_chromium_profiles(user_data):
            profile = BrowserProfile(name=prof_path.name, path=prof_path)
            for sub_path, label in CHROMIUM_CACHE_SUBDIRS.items():
                cache_path = prof_path / sub_path
                entry = self._scan_cache_path(cache_path, label)
                profile.caches.append(entry)
            if profile.caches:
                result.profiles.append(profile)

        return result

    def scan_firefox_browser(self, name: str, profiles_dir: Path) -> BrowserScanResult:
        """Scan a Firefox-based browser."""
        exe = BROWSER_EXES.get(name, "")
        result = BrowserScanResult(name=name, engine="firefox")
        result.is_running = self._is_browser_running(exe)

        if not profiles_dir.is_dir():
            result.error = f"Profiles folder not found: {profiles_dir}"
            return result

        for prof_path in self._find_firefox_profiles(profiles_dir):
            profile = BrowserProfile(name=prof_path.name, path=prof_path)
            for sub_path, label in FIREFOX_CACHE_SUBDIRS.items():
                cache_path = prof_path / sub_path
                entry = self._scan_cache_path(cache_path, label)
                profile.caches.append(entry)
            if profile.caches:
                result.profiles.append(profile)

        return result

    def scan(self) -> List[BrowserScanResult]:
        """
        Scan all supported browsers and return results.
        Never raises — always completes with partial results on error.
        """
        results = []
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        appdata = Path(os.environ.get("APPDATA", ""))

        # Chromium browsers
        for bname, rel_path, use_appdata in CHROMIUM_BROWSERS:
            user_data = (appdata if use_appdata else local) / rel_path
            result = self.scan_chromium_browser(bname, user_data, use_appdata)
            if result.profiles or result.error:
                results.append(result)

        # Firefox browsers
        for bname, rel_path in FIREFOX_BROWSERS:
            browser_dir = appdata / rel_path
            profiles_dir = browser_dir / "Profiles"
            result = self.scan_firefox_browser(bname, profiles_dir)
            if result.profiles or result.error:
                results.append(result)

        results.sort(key=lambda r: r.total_bytes, reverse=True)
        return results
```

- [ ] **Step 4: Add convenience function for module-level use**

Before the existing module-level `detect_browsers` function, add:

```python
def scan_browsers_robust() -> List[BrowserScanResult]:
    """Convenience wrapper: scan all browsers using BrowserScanner2."""
    return BrowserScanner2().scan()
```

- [ ] **Step 5: Verify the file still imports correctly**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.cleanup import browser_scanner as bs; r = bs.BrowserScanner2().scan(); print([x.name for x in r])"`

Expected: List of detected browser names (may be empty if none found, but no errors)

---

## Task 2: Update _BrowserCleanupTab to use BrowserScanner2

**Files:**
- Modify: `src/modules/cleanup/tabs/_browser_tab.py:1-234`

- [ ] **Step 1: Change import from bs.detect_browsers() to bs.scan_browsers_robust()**

In `_do_scan()`, change:
```python
# FROM:
self._worker = Worker(lambda _w: bs.detect_browsers())

# TO:
self._worker = Worker(lambda _w: bs.scan_browsers_robust())
```

- [ ] **Step 2: Update `_on_scan_result` to handle new BrowserScanResult structure**

Replace the entire `_on_scan_result` method body. The new result structure has:
- `result.name`, `result.total_bytes` (property)
- `result.is_running`
- `result.profiles[i].name`, `result.profiles[i].total_bytes` (property)
- `result.profiles[i].caches[j].label`, `result.profiles[i].caches[j].size_bytes`, `result.profiles[i].caches[j].locked`

```python
def _on_scan_result(self, results: list):
    self._scanning = False
    self._scan_btn.setEnabled(True)
    self._progress.hide()
    self._tree.clear()

    running = [r.name for r in results if r.is_running]
    if running:
        self._warn.setText(
            f"⚠  Running: {', '.join(running)} — close browser before deleting cache."
        )
        self._warn.show()
    else:
        self._warn.hide()

    total_all = 0
    total_cats = 0
    active = 0
    for result in results:
        if result.total_bytes == 0 and not result.error:
            continue

        # Show browser row even if error
        b_item = QTreeWidgetItem([result.name, cs.format_size(result.total_bytes)])
        b_item.setCheckState(0, Qt.CheckState.Checked)
        b_item.setFlags(
            b_item.flags()
            | Qt.ItemFlag.ItemIsAutoTristate
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        b_item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Color by running state
        if result.is_running:
            b_item.setForeground(0, QBrush(QColor("#ff9800")))
            b_item.setForeground(1, QBrush(QColor("#ff9800")))
        elif result.error:
            b_item.setForeground(0, QBrush(QColor("#f44336")))
            b_item.setForeground(1, QBrush(QColor("#f44336")))
            b_item.setToolTip(0, result.error or "")

        self._tree.addTopLevelItem(b_item)
        b_item.setExpanded(True)
        active += 1

        for profile in result.profiles:
            p_item = QTreeWidgetItem([profile.name, cs.format_size(profile.total_bytes)])
            p_item.setCheckState(0, Qt.CheckState.Checked)
            p_item.setFlags(
                p_item.flags()
                | Qt.ItemFlag.ItemIsAutoTristate
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            p_item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            b_item.addChild(p_item)
            p_item.setExpanded(True)

            for cache in profile.caches:
                if not cache.exists and not cache.locked:
                    continue
                if cache.size_bytes == 0:
                    continue

                label = cache.label
                if cache.locked:
                    label += " 🔒"
                c_item = QTreeWidgetItem([label, cs.format_size(cache.size_bytes)])
                c_item.setCheckState(0, Qt.CheckState.Checked if not cache.locked else Qt.CheckState.Unchecked)
                c_item.setFlags(c_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                c_item.setData(0, Qt.ItemDataRole.UserRole, cache)
                c_item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if cache.locked:
                    c_item.setForeground(0, QBrush(QColor("#888888")))
                    c_item.setToolTip(0, "Cache is locked (browser running or access denied)")
                p_item.addChild(c_item)
                total_cats += 1

            total_all += profile.total_bytes

        # Show browsers with errors but no profiles
        if not result.profiles and result.error:
            e_item = QTreeWidgetItem([f"Error: {result.error}", "—"])
            e_item.setFlags(e_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            e_item.setForeground(0, QBrush(QColor("#f44336")))
            b_item.addChild(e_item)

    # Find locked caches count
    locked_count = sum(r.locked_count for r in results)

    if active == 0:
        self._status.setText("No browser caches found.")
    else:
        parts = [f"{active} browser(s)"]
        parts.append(f"{total_cats} cache(s)")
        parts.append(cs.format_size(total_all))
        if locked_count > 0:
            parts.append(f"({locked_count} locked — browser may be running)")
        self._status.setText(" — ".join(parts))

    self._clean_btn.setEnabled(total_cats > locked_count)
```

- [ ] **Step 3: Update `_collect_checked` to handle CacheEntry objects**

The `CacheEntry` objects from `BrowserScanner2` don't have the same structure as the old `CacheCategory`. Update the method:

```python
def _collect_checked(self) -> list:
    """Collect checked (and not locked) cache entries for deletion."""
    cats = []
    for i in range(self._tree.topLevelItemCount()):
        b = self._tree.topLevelItem(i)
        for j in range(b.childCount()):
            p = b.child(j)
            for k in range(p.childCount()):
                c = p.child(k)
                if c.checkState(0) != Qt.CheckState.Checked:
                    continue
                entry = c.data(0, Qt.ItemDataRole.UserRole)
                if entry is None:
                    continue
                # Skip locked entries
                if hasattr(entry, 'locked') and entry.locked:
                    continue
                cats.append(entry)
    return cats
```

- [ ] **Step 4: Update `_do_clean` to handle the delete**

The old code used `bs.delete_selected(cats)` with `CacheCategory` objects. Now we need a new delete function. First, add `delete_cache_entries` to `browser_scanner.py`.

- [ ] **Step 5: Add `delete_cache_entries` function to browser_scanner.py**

Add after the `EnhancedBrowserScanner.delete_selected` method:

```python
def delete_cache_entries(entries: List[CacheEntry], progress_cb=None) -> Tuple[int, int]:
    """
    Delete selected cache entries (directories or files).

    Args:
        entries: List of CacheEntry objects to delete
        progress_cb: Optional callback(current, total)

    Returns:
        Tuple of (freed_bytes: int, error_count: int)
    """
    freed = 0
    errors = 0
    total = len(entries)
    for i, entry in enumerate(entries):
        if not hasattr(entry, 'path') or not entry.path.exists():
            continue
        try:
            if entry.path.is_dir():
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                entry.path.unlink()
            freed += entry.size_bytes
        except Exception:
            errors += 1
        if progress_cb:
            progress_cb(i + 1, total)
    return freed, errors
```

- [ ] **Step 6: Update _do_clean in _browser_tab.py to use the new delete function**

```python
# FROM:
self._worker = Worker(lambda _w: bs.delete_selected(cats))

# TO:
self._worker = Worker(lambda _w: bs.delete_cache_entries(cats))
```

---

## Task 3: Update _OverviewTab to use BrowserScanner2

**Files:**
- Modify: `src/modules/cleanup/tabs/_overview_tab.py:167-213`

- [ ] **Step 1: Change the browser group scan to use scan_browsers_robust**

In `_make_cb` inside `_do_scan_all`, update the browser group branch:

```python
# FROM (around line 171-180):
if fns is None:
    try:
        browsers = bs.detect_browsers()
        for b in browsers:
            total += b.total_bytes
            safe  += b.total_bytes
            count += sum(len(p.categories) for p in b.profiles)
    except Exception as e:
        logger.warning(f"Browser scan failed: {e}")

# TO:
if fns is None:
    try:
        results = bs.scan_browsers_robust()
        for r in results:
            total += r.total_bytes
            safe  += r.total_bytes   # browser caches always safe to clean
            count += r.total_caches
    except Exception as e:
        logger.warning(f"Browser scan failed: {e}")
```

- [ ] **Step 2: Verify the overview tab still builds**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.cleanup.tabs._overview_tab import _OverviewTab; print('OK')"`

---

## Task 4: Verify end-to-end — run the full cleanup module

**Files:**
- Test: `src/modules/cleanup/cleanup_module.py`

- [ ] **Step 1: Run syntax check on entire cleanup module**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.cleanup import cleanup_module; print('Module imports OK')"`

- [ ] **Step 2: Run a quick browser scan directly**

Run: `python -c "
import sys; sys.path.insert(0, 'src')
from modules.cleanup import browser_scanner as bs
results = bs.scan_browsers_robust()
for r in results:
    print(f'{r.name}: {r.total_bytes} bytes, {r.total_caches} caches, running={r.is_running}')
    for p in r.profiles:
        print(f'  {p.name}: {p.total_bytes} bytes, {len(p.caches)} cache dirs')
        for c in p.caches:
            if c.size_bytes > 1024:
                print(f'    {c.label}: {c.size_bytes} bytes (locked={c.locked})')
"`

Expected: Shows all detected browsers, their profiles, cache dirs with sizes.

- [ ] **Step 3: Commit Phase 1**

```bash
git add src/modules/cleanup/browser_scanner.py src/modules/cleanup/tabs/_browser_tab.py src/modules/cleanup/tabs/_overview_tab.py
git commit -m "feat(cleanup): add BrowserScanner2 with comprehensive profile and cache enumeration

- BrowserScanner2 scans all modern Chromium cache locations (Cache, Cache2,
  Code Cache, GPUCache, Media Cache, ShaderCache, etc.) per profile
- Enumerates profiles via Local State info_cache + directory scan fallback
- Detects running browsers via psutil and marks caches as locked
- _BrowserCleanupTab updated to show locked items greyed-out with warning
- _OverviewTab wired to BrowserScanner2 for accurate totals
- Adds delete_cache_entries() for safe deletion of CacheEntry objects
"
```

---

## Phase 1 Complete

After Task 4, Phase 1 is done. Run the app and verify:
1. Browser Caches tab shows all Chrome/Edge profiles with actual byte sizes
2. Running Chrome/Edge shows an orange warning banner
3. Locked cache entries are greyed out and cannot be selected for deletion
4. Overview tab shows browser cache totals alongside other categories
5. Delete operation correctly frees space

**Then proceed to Phase 2 spec for new cleanup features.**