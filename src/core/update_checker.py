"""
update_checker.py — Checks GitHub Releases API for a newer version.

Usage:
    checker = UpdateChecker("owner/repo", current_version="1.0.0")
    result = checker.check()   # blocks briefly (network)
    if result.update_available:
        print(result.latest_version, result.release_url)
"""
import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Optional


@dataclass
class UpdateResult:
    update_available: bool
    current_version: str
    latest_version: str
    release_url: str
    release_notes: str
    error: Optional[str] = None


def _parse_version(v: str):
    """Return a comparable tuple from a version string like '1.2.3' or 'v1.2.3'."""
    v = v.lstrip("v").strip()
    parts = re.split(r"[.\-]", v)
    result = []
    for p in parts[:3]:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    while len(result) < 3:
        result.append(0)
    return tuple(result)


class UpdateChecker:
    API_URL = "https://api.github.com/repos/{repo}/releases/latest"
    TIMEOUT = 8  # seconds

    def __init__(self, repo: str, current_version: str):
        self._repo = repo
        self._current = current_version

    def check(self) -> UpdateResult:
        url = self.API_URL.format(repo=self._repo)
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "WinClientTool-UpdateChecker/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return UpdateResult(
                update_available=False,
                current_version=self._current,
                latest_version=self._current,
                release_url="",
                release_notes="",
                error=str(e),
            )

        latest_tag = data.get("tag_name", "")
        release_url = data.get("html_url", "")
        release_notes = data.get("body", "")
        latest_version = latest_tag.lstrip("v")

        update_available = (
            _parse_version(latest_version) > _parse_version(self._current)
        )
        return UpdateResult(
            update_available=update_available,
            current_version=self._current,
            latest_version=latest_version,
            release_url=release_url,
            release_notes=release_notes,
        )
