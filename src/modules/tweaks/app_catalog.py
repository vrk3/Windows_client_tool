# src/modules/tweaks/app_catalog.py
import json
import logging
import os
import subprocess
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# AppX packages that must never appear in a removal queue
PROTECTED_APPS_DEFAULT = {
    "Microsoft.OneDriveSync",
    "Microsoft.Office.OneNote",
    "Microsoft.WindowsStore",
    "Microsoft.Windows.Photos",
}


class AppCatalog:
    """Manages the installable app catalog and installed-app detection.

    Catalog source: definitions/app_catalog.json (winget-installable apps).
    Installed detection: `winget list` output + PowerShell Get-AppxPackage.
    """

    def __init__(self, catalog_path: Optional[str] = None):
        if catalog_path is None:
            catalog_path = os.path.join(
                os.path.dirname(__file__), "definitions", "app_catalog.json"
            )
        with open(catalog_path, encoding="utf-8") as f:
            self.entries: List[Dict] = json.load(f)

    def categories(self) -> List[str]:
        """Return sorted unique category names."""
        return sorted({e["category"] for e in self.entries})

    def filter_by_category(self, category: str) -> List[Dict]:
        if category == "All":
            return self.entries
        return [e for e in self.entries if e["category"] == category]

    # ------------------------------------------------------------------
    # Detection helpers (called from worker threads)
    # ------------------------------------------------------------------

    def detect_installed_winget(self) -> Set[str]:
        """Run `winget list` and return set of installed winget IDs."""
        try:
            result = subprocess.run(
                ["winget", "list", "--accept-source-agreements"],
                capture_output=True, text=True, timeout=30, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return self._parse_winget_list(result.stdout)
        except Exception as e:
            logger.warning("winget list failed: %s", e)
            return set()

    def _parse_winget_list(self, output: str) -> Set[str]:
        """Parse winget list text output → set of IDs (second column)."""
        ids: Set[str] = set()
        lines = output.splitlines()
        # Skip header lines (Name/Id/Version header + separator)
        data_started = False
        for line in lines:
            if line.startswith("---") or line.startswith("==="):
                data_started = True
                continue
            if not data_started:
                continue
            parts = line.split()
            # winget list columns: Name ... Id Version [Source]
            # ID column is the one that looks like Publisher.Product
            for part in parts:
                if "." in part and not part.startswith("-") and len(part) > 3:
                    ids.add(part)
                    break
        return ids

    def detect_installed_appx(self) -> Set[str]:
        """Return set of installed AppX package family names via PowerShell."""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-AppxPackage | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=20, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return self._parse_appx_list(result.stdout)
        except Exception as e:
            logger.warning("Get-AppxPackage failed: %s", e)
            return set()

    def _parse_appx_list(self, output: str) -> Set[str]:
        return {line.strip() for line in output.splitlines() if line.strip()}

    def detect_installed_win32(self) -> Set[str]:
        """Return set of display names from registry Uninstall keys."""
        import winreg
        names: Set[str] = set()
        paths = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, path in paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_name) as sub:
                                display_name, _ = winreg.QueryValueEx(sub, "DisplayName")
                                if display_name:
                                    names.add(display_name)
                        except OSError:
                            continue
            except OSError:
                continue
        return names

    # ------------------------------------------------------------------
    # Install / remove (called from worker threads)
    # ------------------------------------------------------------------

    def install_app(self, winget_id: str,
                    on_output: Optional[callable] = None) -> bool:
        """Run winget install. Streams output via on_output callback."""
        return self._run_winget(
            ["winget", "install", winget_id, "--silent",
             "--accept-package-agreements", "--accept-source-agreements"],
            on_output,
        )

    def remove_app_winget(self, winget_id: str,
                          on_output: Optional[callable] = None) -> bool:
        return self._run_winget(
            ["winget", "uninstall", winget_id, "--silent"],
            on_output,
        )

    def _appx_present(self, package_name: str,
                      on_output: Optional[callable] = None) -> Optional[bool]:
        """Is this package installed? None means the question was not answered.

        Asks for the WHOLE list and matches in Python, rather than
        `Get-AppxPackage '<name>'`. The unfiltered form is the one that
        populates the UI and is known to work in the app's own context; the
        filtered form returned nothing there while the full list contained the
        package, which is how a removal came to do nothing at all in silence.

        The return code and stderr are checked, because **empty output from a
        command that failed is not evidence of absence** — that rule is
        everywhere in this codebase, and reading empty stdout as "the package
        is gone" is exactly how a removal that never happened got reported as
        a success.
        """
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-AppxPackage | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        complaint = (result.stderr or "").strip()
        if result.returncode != 0 or complaint:
            if on_output:
                on_output(f"could not read the installed package list "
                          f"(exit {result.returncode}): "
                          f"{complaint or 'no output'}")
            return None
        names = {line.strip() for line in (result.stdout or "").splitlines()
                 if line.strip()}
        if not names:
            if on_output:
                on_output("could not read the installed package list: it came "
                          "back empty, which no Windows install ever is")
            return None
        return package_name in names

    def remove_appx(self, package_name: str,
                    on_output: Optional[callable] = None) -> bool:
        """Remove a package, and return whether it is actually gone.

        True only on positive evidence: the package was listed before, and is
        not listed afterwards. Everything else is False with a reason --
        including "the list could not be read", because an unanswered question
        is not a success.
        """
        before = self._appx_present(package_name, on_output)
        if before is None:
            return False
        if not before:
            # `Get-AppxPackage 'X' | Remove-AppxPackage` with nothing matching
            # removes nothing, prints nothing and exits 0. Saying so beats
            # running it and reporting whatever silence comes back.
            if on_output:
                on_output(f"{package_name} is not visible as an installed "
                          "package, so there is nothing here to remove")
            return False

        cmd = f"Get-AppxPackage '{package_name}' | Remove-AppxPackage"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if on_output:
            for line in (result.stdout + result.stderr).splitlines():
                on_output(line)

        after = self._appx_present(package_name, on_output)
        if after is None:
            if on_output:
                on_output(f"could not confirm whether {package_name} was "
                          "removed")
            return False
        if after:
            if on_output:
                on_output(f"{package_name} is still installed after the "
                          "removal")
            return False
        return True

    def _run_winget(self, args: List[str],
                    on_output: Optional[callable]) -> bool:
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                if on_output:
                    on_output(line.rstrip())
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            logger.error("winget command failed: %s", e)
            if on_output:
                on_output(f"Error: {e}")
            return False
