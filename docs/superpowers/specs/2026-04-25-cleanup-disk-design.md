# Cleanup & Disk Module — Phase 1 & 2 Design Spec

**Date:** 2026-04-25
**Principle:** Maximum cleanup + minimum risk

---

## Phase 1: Fix the Browser Scanner

### Root Cause
`EnhancedBrowserScanner._chromium_profile_names()` only reads profile names from `Local State`'s `info_cache`. If `Local State` is missing, corrupted, or uses unexpected profile names, no profiles are found. Additionally, `CHROMIUM_CACHE_CATEGORIES` lists only 7 cache locations — Chrome on modern Windows uses many more (Cache2, Code Cache, GPUCache, Media Cache, ShaderCache, GrShaderCache, etc.).

### Design: BrowserScanner2

New class `BrowserScanner2` replaces `EnhancedBrowserScanner` in `browser_scanner.py`. The old `EnhancedBrowserScanner` is kept for backward compatibility but `CleanupModule` uses `BrowserScanner2`.

#### Profile Enumeration (Maximum Coverage)
```python
def _find_chromium_profiles(user_data: Path) -> List[Path]:
    profiles = []
    seen = set()

    # 1. Local State info_cache (canonical source)
    local_state = user_data / "Local State"
    if local_state.is_file():
        try:
            data = json.load(open(local_state, encoding="utf-8", errors="replace"))
            cache = data.get("profile", {}).get("info_cache", {})
            for name in cache:
                p = user_data / name
                if p.is_dir() and p not in seen:
                    profiles.append(p)
                    seen.add(p)
        except Exception:
            pass

    # 2. Scan user_data dir for any folder looking like a profile
    # Pattern: "Default", "Profile 1", "Profile 2", "Profile 3", etc.
    # Also: named profiles like "Profile 4", "Profile 5"
    profile_patterns = ["Default", "System Profile"]
    for entry in os.scandir(user_data):
        if not entry.is_dir(follow_symlinks=False):
            continue
        entry_path = Path(entry.path)
        if entry_path in seen:
            continue
        name_lower = entry.name.lower()
        # Matches: "Default", "Profile X", "Profile X (1)", "System Profile"
        if name_lower == "default":
            profiles.append(entry_path)
            seen.add(entry_path)
        elif name_lower.startswith("profile"):
            profiles.append(entry_path)
            seen.add(entry_path)

    return profiles
```

#### Cache Category Enumeration (Maximum Cleanup)
```python
# All modern Chrome/Edge cache locations
CACHE_SUBDIRS = {
    "Cache":              "HTTP Cache (legacy)",
    "Cache2":             "HTTP Cache v2",
    "Code Cache":         "Compiled JS/WASM cache",
    "GPUCache":           "GPU shader cache",
    "Media Cache":        "Video/audio media cache",
    "blob_storage":       "Blob storage",
    "ShaderCache":        "Graphics shader cache",
    "GrShaderCache":      "General shader cache",
    "DawnCache":          "Dawn WebGPU cache",
    "独立缓存":            "Chinese: independent cache",
    "Crowd Deny":         "Crowd Deny database",
    "Extension Cache":    "Extension manifest + resource cache",
    "Local App Settings": "Local app settings",
    "Local Storage":     "Local Storage database",
    "Sessions":           "Tab sessions",
    "Tabs":               "Tab data",
    "Web Application History": "Web app history",
    r"Crashpad\reports":  "Crash reports",
    r"Crashpad\pending":  "Pending crash reports",
    r"GrShaderCache\GPUCache": "GPU shader cache (sub)",
    r"ShaderCache\GPUCache": "GPU shader cache (sub)",
}
```

#### Running Browser Detection
```python
BROWSER_EXES = {
    "Chrome":    "chrome.exe",
    "Edge":      "msedge.exe",
    "Brave":     "brave.exe",
    "Vivaldi":   "vivaldi.exe",
    "Opera":     "opera.exe",
}

def detect_running():
    import psutil
    running = set()
    for name, exe in BROWSER_EXES.items():
        for p in psutil.process_iter(["name"]):
            try:
                if p.info["name"] and p.info["name"].lower() == exe.lower():
                    running.add(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    return running
```

#### Size Calculation
- Use `shutil.disk_usage()` equivalent per folder
- Walk only 1 level deep per cache subfolder (don't re-scan nested directories)
- Skip folders < 1KB (likely empty placeholder)
- For large folders (>500MB), calculate size with progress indicator

#### Results Structure
```python
@dataclass
class CacheEntry:
    profile: str          # "Default", "Profile 2", etc.
    category: str         # "Code Cache"
    path: Path
    size_bytes: int
    exists: bool
    locked: bool          # True if browser running / access denied

@dataclass
class BrowserProfile:
    name: str
    path: Path
    caches: List[CacheEntry]
    total_bytes: int

@dataclass
class BrowserResult:
    name: str
    engine: str
    is_running: bool
    profiles: List[BrowserProfile]
    total_bytes: int
    error_message: Optional[str]  # "access denied", "browser running", etc.
```

#### Delete Logic
- Confirm if browser is running (block delete, show error)
- For locked files, skip and report
- Use `shutil.rmtree()` with `ignore_errors=True` as fallback
- Verify post-delete by re-scanning

### UI: _BrowserCleanupTab Changes
- Show "Browser is running" warning banner with orange styling
- Show per-profile total + expandable tree
- Add "Refresh" button (re-run scanner)
- "Select All" checks all profiles + all cache types
- Status bar: "5 profiles, 38 cache entries, 22.4 GB" (never "No caches found")
- If total_bytes == 0 but browser IS installed, show: "Found browser but no cache data (browser may be running or profile data is empty)"

### Integration with CleanupModule
- `_BrowserCleanupTab` uses `BrowserScanner2`
- `_OverviewTab` also shows browser cache total (import from browser_scanner)
- Add `get_browser_cache_total()` function that returns just the size for overview

---

## Phase 2: Add Missing Cleanup Features

### New Scan Functions (added to cleanup_scanner.py)

| Function | Target | Safety |
|---|---|---|
| `scan_duplicate_photos` | Same-filename + perceptual hash (pHash) for visually identical images | safe |
| `scan_empty_folders` | Folders containing zero files (recursive) | safe |
| `scan_old_files` | Files not accessed in N days (user-configurable) | caution |
| `scan_font_cleanup` | Unused/duplicate system fonts | caution |
| `scan_windows_old` | Windows.old from failed upgrade (already exists, needs better detection) | safe |

### Duplicate Photo Finder
```python
def scan_duplicate_photos(min_age_days: int = 0, min_size: int = 10_000) -> ScanResult:
    """
    Find duplicate images using 2-phase algorithm:
    1. Group by exact file size
    2. For groups with 2+ files, compute perceptual hash (imagehash library)
       If pHash distance < 5, treat as duplicate
    3. Also check exact MD5 for files < 1MB (fast)
    """
```

**Dependencies:** `imagehash` library (pip install imagehash pillow)

### Empty Folder Finder
```python
def scan_empty_folders(min_age_days: int = 0) -> ScanResult:
    """
    Walk entire system drive (or user-selected folder) and find folders
    that contain zero files. Nested empty folders count.
    Safety: only flags folders, never auto-deletes without confirmation.
    """
```

### Old Files Finder
```python
def scan_old_files(root_path: str, min_days: int = 365) -> ScanResult:
    """
    User selects a root folder (e.g., Downloads, Documents).
    Find all files not accessed in min_days.
    Shows file count per folder to help user decide.
    Risk: only flags, not auto-selects.
    """
```

### Font Cleanup
```python
def scan_font_cleanup() -> ScanResult:
    """
    List all installed fonts from C:\Windows\Fonts.
    Find duplicates (same font name, different file).
    Flag unused fonts (not in font cache for 90+ days).
    Requires admin — SYSTEM\FonFont registry access.
    """
```

### Cleanup Module Changes (cleanup_module.py)

Add 4 new tabs:

**9. Duplicate Finder**
- Uses existing `duplicate_finder_module.py` logic but as a cleanup tab
- Or: add a "Add to Cleanup" button in the existing duplicate finder that feeds into this tab

**10. Empty Folders**
- Scanner for empty folders
- "Delete Empty Folders" button with folder count confirmation

**11. Old Files**
- User selects folder → sets age threshold → scan
- Shows top-level folders with old-file counts

**12. Font Manager** (low priority, Phase 2b)
- View installed fonts, flag duplicates, flag unused

---

## Risk Management

### Never-Do List (Low Risk Rules)
1. Never delete files from `C:\Windows\System32`
2. Never delete files from `C:\Windows\WinSxS` directly — use only DISM
3. Never delete anything from `Program Files` or `Program Files (x86)` without explicit user selection
4. Never auto-select items marked "danger" safety
5. Never block on errors — always complete the scan and report issues
6. Never show 0 bytes when data might exist — investigate and explain

### Confirmation Thresholds
- < 100 MB: no confirmation needed
- 100 MB – 500 MB: "About to delete X — continue?"
- 500 MB – 2 GB: "This will permanently delete X — confirm"
- > 2 GB: "This is a large deletion (X). Are you sure?" + checkbox "I understand"
- Any "danger" safety item: always require explicit confirmation regardless of size

### Browser Running Policy
- If any browser is running: show warning banner, block deletion of browser caches
- Allow deleting non-browser cleanup categories while browsers are running (temp files, etc.)
- Show count of locked/inaccessible items separately from cleanable items

---

## File Changes

| File | Action |
|---|---|
| `browser_scanner.py` | Add `BrowserScanner2` class, keep old `EnhancedBrowserScanner` for compatibility |
| `cleanup_module.py` | Wire `_BrowserCleanupTab` to use `BrowserScanner2` |
| `tabs/_browser_tab.py` | Update to handle new `CacheEntry` structure, show locked items, better status |
| `tabs/_overview_tab.py` | Import browser cache total, show in overview summary |
| `cleanup_scanner.py` | Add 4 new scan functions: `scan_duplicate_photos`, `scan_empty_folders`, `scan_old_files`, `scan_font_cleanup` |
| `requirements.txt` | Add `imagehash` dependency |