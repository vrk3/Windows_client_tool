# -*- coding: utf-8 -*-
"""
Enhanced Browser Caches with Browser Selector

Features:
- Browser selector dropdown
- Profile-level cleanup
- Running application detection
- Smart warnings
"""

# Module-level convenience function — delegates to EnhancedBrowserScanner
def detect_browsers(all_browsers: bool = True, browser_name: str = "All"):
    """Detect browsers and their cache sizes. Convenience wrapper for EnhancedBrowserScanner."""
    return EnhancedBrowserScanner().detect_browsers(all_browsers=all_browsers, browser_name=browser_name)


def delete_selected(categories, progress_cb=None):
    """Delete selected cache categories. Wrapper for EnhancedBrowserScanner.delete_selected."""
    return EnhancedBrowserScanner().delete_selected(categories, progress_cb=progress_cb)

import json
import os
import shutil
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass


# Browser definitions with paths
CHROMIUM_BROWSERS = [
    ("Brave", r"BraveSoftware\Brave-Browser\User Data", False),
    ("Chrome", r"Google\Chrome\User Data", False),
    ("Edge", r"Microsoft\Edge\User Data", False),
    ("Vivaldi", r"Vivaldi\User Data", False),
    ("Thorium", r"Thorium\User Data", False),
    ("Chromium", r"Chromium\User Data", False),
    ("Yandex", r"Yandex\YandexBrowser\User Data", False),
    ("Opera", r"Opera Software\Opera Stable", True),
    ("Opera GX", r"Opera Software\Opera GX Stable", True),
]

FIREFOX_BROWSERS = [
    ("Firefox", r"Mozilla\Firefox"),
    ("LibreWolf", r"LibreWolf"),
    ("Waterfox", r"Waterfox"),
    ("Pale Moon", r"Moonchild Productions\Pale Moon"),
]

# Cache categories for Chromium
CHROMIUM_CACHE_CATEGORIES = [
    ("Cache", "HTTP Cache"),
    ("Cache2", "HTTP Cache v2"),
    ("Code Cache", "Compiled JS & WASM"),
    ("GPU Cache", "GPU Shader Cache"),
    ("Media Cache", "Media Cache"),
    ("blob_storage", "Blob Storage"),
    (r"Crashpad\reports", "Crash Reports"),
]

# Cache categories for Firefox
FIREFOX_CACHE_CATEGORIES = [
    ("cache2", "HTTP Cache"),
    ("cache", "Cache (legacy)"),
    ("offlineCache", "Offline Cache"),
    ("thumbnails", "Page Thumbnails"),
    ("startupCache", "Startup Cache"),
    (r"crashes\submitted", "Submitted Crashes"),
    (r"crashes\pending", "Pending Crashes"),
    ("minidumps", "Minidumps"),
]

# Browser executable mappings
EXE_MAP = {
    "Brave": "brave.exe",
    "Chrome": "chrome.exe",
    "Edge": "msedge.exe",
    "Vivaldi": "vivaldi.exe",
    "Thorium": "thorium.exe",
    "Chromium": "chrome.exe",
    "Yandex": "browser.exe",
    "Opera": "opera.exe",
    "Opera GX": "opera.exe",
    "Firefox": "firefox.exe",
    "LibreWolf": "librewolf.exe",
    "Waterfox": "waterfox.exe",
    "Pale Moon": "palemoon.exe",
}


@dataclass
class CacheCategory:
    """Represents a cache category with path and size."""

    label: str
    path: Path
    size_bytes: int = 0
    exists: bool = False


@dataclass
class BrowserProfile:
    """Represents a browser user profile."""

    name: str
    path: Path
    categories: List[CacheCategory] = None

    def __post_init__(self):
        self.categories = self.categories or []
        self.total_bytes: int = 0


@dataclass
class BrowserResult:
    """Represents a browser result with profiles."""

    name: str
    engine: str  # "chromium" | "firefox"
    profiles: List[BrowserProfile] = None
    is_running: bool = False
    total_bytes: int = 0

    def __post_init__(self):
        self.profiles = self.profiles or []


class EnhancedBrowserScanner:
    """Enhanced browser cache scanner with browser selector."""

    def _is_running(self, exe: str) -> bool:
        """Check if browser is currently running."""
        try:
            import psutil

            exe_lower = exe.lower()
            for p in psutil.process_iter(["name"]):
                try:
                    if (p.info["name"] or "").lower() == exe_lower:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass
        return False

    def _chromium_profile_names(self, user_data: Path) -> List[str]:
        """Get list of Chromium profiles."""
        names = []
        local_state = user_data / "Local State"
        if local_state.is_file():
            try:
                with open(local_state, encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
                cache = data.get("profile", {}).get("info_cache", {})
                names = [k for k in cache if (user_data / k).is_dir()]
            except Exception:
                pass

        # Fallback to Default profile
        if not names and (user_data / "Default").is_dir():
            names = ["Default"]
        return names

    def detect_browsers(
        self, all_browsers: bool = True, browser_name: str = "All"
    ) -> List[BrowserResult]:
        """
        Detect browsers and their cache sizes.

        Args:
            all_browsers: True = show all, or specific browser name
            browser_name: Specific browser to show
        """
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        appdata = Path(os.environ.get("APPDATA", ""))
        results = []

        # Chromium-based browsers
        for name, rel, use_appdata in CHROMIUM_BROWSERS:
            if not browser_name or all_browsers:
                user_data = (appdata if use_appdata else local) / rel
                if not user_data.is_dir():
                    continue

                browser = BrowserResult(
                    name=name,
                    engine="chromium",
                    is_running=self._is_running(EXE_MAP.get(name, "")),
                )

                for prof_name in self._chromium_profile_names(user_data):
                    prof_path = user_data / prof_name
                    cats = self._scan_chromium_profile(prof_path)
                    total = sum(c.size_bytes for c in cats)
                    browser.profiles.append(
                        BrowserProfile(
                            name=prof_name,
                            path=prof_path,
                            categories=cats,
                            total_bytes=total,
                        )
                    )

                browser.total_bytes = sum(p.total_bytes for p in browser.profiles)
                if browser.total_bytes > 0:
                    results.append(browser)

        # Firefox-based browsers
        if browser_name != "Edge" or all_browsers:
            for name, rel in FIREFOX_BROWSERS:
                if browser_name and browser_name != name:
                    continue

                browser_dir = appdata / rel
                if not browser_dir.is_dir():
                    continue

                profiles_dir = browser_dir / "Profiles"
                if not profiles_dir.is_dir():
                    continue

                browser = BrowserResult(
                    name=name,
                    engine="firefox",
                    is_running=self._is_running(EXE_MAP.get(name, "")),
                )

                for prof_path in sorted(
                    p for p in profiles_dir.iterdir() if p.is_dir()
                ):
                    cats = self._scan_firefox_profile(prof_path)
                    total = sum(c.size_bytes for c in cats)
                    browser.profiles.append(
                        BrowserProfile(
                            name=prof_path.name,
                            path=prof_path,
                            categories=cats or [],
                            total_bytes=total,
                        )
                    )

                browser.total_bytes = sum(p.total_bytes for p in browser.profiles)
                if browser.total_bytes > 0:
                    results.append(browser)

        # Sort by size descending
        results.sort(key=lambda b: b.total_bytes, reverse=True)
        return results

    def _scan_chromium_profile(self, prof_path: Path) -> List[CacheCategory]:
        """Scan Chromium profile for cache categories."""
        categories = []
        for rel_sub, label in CHROMIUM_CACHE_CATEGORIES:
            p = prof_path / rel_sub
            exists = p.exists()
            size = self._dir_size(p) if exists else 0
            categories.append(
                CacheCategory(label=label, path=p, size_bytes=size, exists=exists)
            )
        return categories

    def _scan_firefox_profile(self, prof_path: Path) -> List[CacheCategory]:
        """Scan Firefox profile for cache categories."""
        categories = []
        for rel_sub, label in FIREFOX_CACHE_CATEGORIES:
            p = prof_path / rel_sub
            exists = p.exists()
            size = self._dir_size(p) if exists else 0
            categories.append(
                CacheCategory(label=label, path=p, size_bytes=size, exists=exists)
            )
        return categories

    def _dir_size(self, path: Path) -> int:
        """Calculate directory size."""
        total = 0
        try:
            for entry in path.rglob("*"):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
        return total

    def delete_selected(
        self, categories: List[CacheCategory], progress_cb=None
    ) -> Tuple[int, int]:
        """Delete selected cache categories.

        Returns:
            Tuple of (freed_bytes: int, error_count: int)
        """
        freed = 0
        errors = 0
        for i, cat in enumerate(categories):
            if cat.path.exists():
                try:
                    if cat.path.is_dir():
                        shutil.rmtree(cat.path, ignore_errors=False)
                    else:
                        cat.path.unlink()
                    freed += cat.size_bytes
                except Exception as e:
                    errors += 1
            if progress_cb:
                progress_cb(i + 1)
        return freed, errors
