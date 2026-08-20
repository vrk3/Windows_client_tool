# Windows Debloat Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows Debloat module with an apps tab (120+ removable UWP apps), privacy/telemetry tab, and AI features tab — using the existing TweakEngine for registry/service/appx operations.

**Architecture:** A new `DebloatModule` in `ModuleGroup.OPTIMIZE` with 3 tabs. The Apps tab uses a `debloat_scanner.py` to detect installed bloatware via `Get-AppxPackage`. Privacy and AI tabs load existing + new tweak definition files. `TweakEngine` is extended with `_apply_scheduled_task()` and `detect_status()` is extended to cover `appx` and `scheduled_task` types.

**Tech Stack:** PyQt6, TweakEngine (existing), BackupService (existing), win32service, subprocess

---

## File Map

```
src/modules/debloat/
  __init__.py                          — package init
  debloat_module.py                    — BaseModule + 3-tab UI widget
  debloat_scanner.py                   — app detection (Get-AppxPackage)
  debloat_search_provider.py            — SearchProvider stub

src/modules/tweaks/definitions/
  debloat.json                         — 120+ appx removal entries (NEW)
  ai_features.json                    — 5 new AI feature entries (NEW)
  navigation.json                     — 4 nav pane entries (NEW)

src/modules/tweaks/
  tweak_engine.py                      — add _apply_scheduled_task(), extend detect_status()
  preset_manager.py                    — add 4 debloat presets

src/main.py                            — register DebloatModule
```

---

## Task 1: TweakEngine — add scheduled task step type and extend detect_status

**Files:**
- Modify: `src/modules/tweaks/tweak_engine.py:76-87` (add step type), `src/modules/tweaks/tweak_engine.py:158-186` (extend detect_status)

- [ ] **Step 1: Add CREATE_NO_WINDOW to _apply_appx and add _apply_scheduled_task**

Read the current `_apply_appx` method and replace it with the following (add CREATE_NO_WINDOW, add `_apply_scheduled_task`, extend `_apply_step`):

```python
def _apply_appx(self, step: Dict, rp_id: str) -> StepRecord:
    pkg = step["package"]
    self._backup.backup_appx_package(pkg, rp_id)
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-AppxPackage '{pkg}' | Remove-AppxPackage"],
        check=False, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return StepRecord("appx", pkg, pkg, None)

def _apply_scheduled_task(self, step: Dict, rp_id: str) -> StepRecord:
    """Disable a scheduled task. Records the current state for revert."""
    task_name = step["task_name"]
    # Query current state
    before = "Unknown"
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            if line.startswith("Status:"):
                before = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    subprocess.run(
        ["schtasks", "/change", "/tn", task_name, "/disable"],
        check=False, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return StepRecord("scheduled_task", task_name, before, "Disabled")
```

- [ ] **Step 2: Update _apply_step to dispatch scheduled_task**

In `_apply_step`, after the `appx` line add:
```python
elif step_type == "scheduled_task":
    return self._apply_scheduled_task(step, rp_id)
```

- [ ] **Step 3: Extend detect_status() to cover appx and scheduled_task**

Replace the current `detect_status()` method body (lines 158-186) with:
```python
def detect_status(self, tweak: Dict) -> str:
    """Return 'applied' | 'not_applied' | 'unknown' from first step."""
    steps = tweak.get("steps", [])
    if not steps:
        return "unknown"
    step = steps[0]
    try:
        if step["type"] == "registry":
            hive, sub = _parse_key(step["key"])
            with winreg.OpenKey(hive, sub) as k:
                val, _ = winreg.QueryValueEx(k, step.get("value", ""))
            return "applied" if val == step["data"] else "not_applied"
        elif step["type"] == "service":
            import win32service
            hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            hs = win32service.OpenService(hscm, step["name"],
                                          win32service.SERVICE_QUERY_CONFIG)
            config = win32service.QueryServiceConfig(hs)
            current = config[1]
            win32service.CloseServiceHandle(hs)
            win32service.CloseServiceHandle(hscm)
            _st = step.get("start_type", "")
            expected = int(_st) if isinstance(_st, int) else _START_TYPE_MAP.get(str(_st).lower(), -1)
            return "applied" if current == expected else "not_applied"
        elif step["type"] == "appx":
            pkg = step["package"]
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-AppxPackage '{pkg}' -ErrorAction SilentlyContinue | Select-Object -First 1 Name"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return "not_applied" if result.stdout.strip() else "applied"
        elif step["type"] == "scheduled_task":
            task_name = step["task_name"]
            result = subprocess.run(
                ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Status:"):
                    state = line.split(":", 1)[1].strip()
                    return "applied" if state == "Disabled" else "not_applied"
            return "unknown"
    except OSError:
        return "unknown"
    except Exception:
        return "unknown"
    return "unknown"
```

- [ ] **Step 4: Commit**

```bash
git add src/modules/tweaks/tweak_engine.py
git commit -m "$(cat <<'EOF'
feat(tweaks): add _apply_scheduled_task, extend detect_status for appx/scheduled_task

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: New Tweak Definition Files (ai_features.json, navigation.json)

**Files:**
- Create: `src/modules/tweaks/definitions/ai_features.json`
- Create: `src/modules/tweaks/definitions/navigation.json`

- [ ] **Step 1: Write ai_features.json**

```json
[
  {
    "id": "disable_click_to_do",
    "name": "Disable Click To Do",
    "description": "Disables Windows 11 24H2 Click To Do AI feature that analyzes screen content.",
    "category": "AI Features", "risk": "low", "requires_admin": true,
    "steps": [{"type": "registry", "key": "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsAI", "value": "DisableClickToDo", "data": 1, "kind": "DWORD"}]
  },
  {
    "id": "disable_ai_hub",
    "name": "Disable AI Hub",
    "description": "Removes the AI Hub entry from the Windows 11 Start menu.",
    "category": "AI Features", "risk": "low", "requires_admin": true,
    "steps": [{"type": "registry", "key": "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsAI", "value": "DisableAIHub", "data": 1, "kind": "DWORD"}]
  },
  {
    "id": "disable_wsa_fabric",
    "name": "Disable WSAIFabricSvc Service",
    "description": "Disables the AI Fabric service that runs alongside Windows Subsystem for Android.",
    "category": "AI Features", "risk": "medium", "requires_admin": true,
    "steps": [{"type": "service", "name": "WSAIFabricSvc", "start_type": "disabled"}]
  },
  {
    "id": "disable_copilot_edge",
    "name": "Disable Copilot in Edge",
    "description": "Disables Microsoft Copilot sidebar in Microsoft Edge.",
    "category": "AI Features", "risk": "low", "requires_admin": false,
    "steps": [
      {"type": "registry", "key": "HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge", "value": "Sidebar", "data": 0, "kind": "DWORD"},
      {"type": "registry", "key": "HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge", "value": "MicrosoftEdgeShowSidebarFactoryApp", "data": 0, "kind": "DWORD"}
    ]
  },
  {
    "id": "disable_paint_cocreator",
    "name": "Disable AI Cocreator in Paint",
    "description": "Disables the Cocreator AI image generation in Paint.",
    "category": "AI Features", "risk": "low", "requires_admin": false,
    "steps": [{"type": "registry", "key": "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Applets\\Paint\\Settings", "value": "DisableAIFeatures", "data": 1, "kind": "DWORD"}]
  }
]
```

- [ ] **Step 2: Write navigation.json**

```json
[
  {
    "id": "hide_gallery_from_nav",
    "name": "Hide Gallery from Navigation Pane",
    "description": "Removes the Gallery entry from the File Explorer navigation pane.",
    "category": "Navigation Pane", "risk": "low", "requires_admin": false,
    "steps": [{"type": "command", "cmd": "powershell -Command \"Remove-Item -Path 'HKCU:\\Software\\Classes\\CLSID\\{e2a14b52-c05e-4287-a9d0-c520b63a2dee}' -Recurse -Force -ErrorAction SilentlyContinue\""}]
  },
  {
    "id": "hide_3d_objects_from_nav",
    "name": "Hide 3D Objects from Navigation Pane",
    "description": "Removes the 3D Objects entry from This PC in File Explorer.",
    "category": "Navigation Pane", "risk": "low", "requires_admin": false,
    "steps": [{"type": "command", "cmd": "powershell -Command \"Remove-Item -Path 'HKCU:\\Software\\Classes\\CLSID\\{0DB7E03F-A78C-4785-B8E2-BC63DB7D9759}' -Recurse -Force -ErrorAction SilentlyContinue\""}]
  },
  {
    "id": "hide_home_from_nav",
    "name": "Hide Home from Navigation Pane",
    "description": "Removes the Home entry from the File Explorer navigation pane.",
    "category": "Navigation Pane", "risk": "low", "requires_admin": false,
    "steps": [{"type": "command", "cmd": "powershell -Command \"Remove-Item -Path 'HKCU:\\Software\\Classes\\CLSID\\{262F7A5A-3AD3-4D50-B4D4-A1F6B0D5C89E}' -Recurse -Force -ErrorAction SilentlyContinue\""}]
  },
  {
    "id": "hide_duplicate_drives",
    "name": "Hide Duplicate Drive Letters",
    "description": "Removes duplicate drive letter entries from the File Explorer navigation pane.",
    "category": "Navigation Pane", "risk": "low", "requires_admin": false,
    "steps": [{"type": "registry", "key": "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer", "value": "HideDriveLettersWithoutNetDrive", "data": 1, "kind": "DWORD"}]
  }
]
```

- [ ] **Step 3: Commit**

```bash
git add src/modules/tweaks/definitions/ai_features.json src/modules/tweaks/definitions/navigation.json
git commit -m "$(cat <<'EOF'
feat(tweaks): add ai_features.json (5 entries) and navigation.json (4 entries)

Covers: Click-to-Do, AI Hub, WSAIFabricSvc, Copilot in Edge,
Paint AI, and navigation pane tweaks.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: debloat.json — 120+ App Removal Entries

**Files:**
- Create: `src/modules/tweaks/definitions/debloat.json`

- [ ] **Step 1: Write debloat.json with all 120+ entries**

Create `src/modules/tweaks/definitions/debloat.json` with the following structure and entries. This is a large JSON file — write the complete content:

```json
[
  {"id": "remove_bing_weather", "name": "Bing Weather", "description": "Weather app with ad-powered news feed.", "category": "Bing Apps", "risk": "low", "requires_admin": true, "package": "Microsoft.BingWeather", "steps": [{"type": "appx", "package": "Microsoft.BingWeather", "action": "remove"}]},
  ... (all entries below — copy them verbatim)
]
```

Full entries to include (from Win11Debloat App Removal wiki):

**Bing Apps:**
- Microsoft.BingWeather, Microsoft.BingNews, Microsoft.BingFinance, Microsoft.BingSports, Microsoft.BingTravel, Microsoft.BingFoodAndDrink, Microsoft.BingHealthAndFitness, Microsoft.BingTranslator, Microsoft.BingSearch

**System Utilities:**
- Microsoft.WindowsCalculator, Microsoft.WindowsCamera, Microsoft.WindowsAlarms, Microsoft.ScreenSketch, Microsoft.WindowsNotepad, Microsoft.Paint, Microsoft.WindowsSoundRecorder, MicrosoftCorporationII.QuickAssist, Microsoft.MicrosoftStickyNotes, Microsoft.WindowsTerminal, Clipchamp.Clipchamp, Microsoft.MicrosoftJournal

**Microsoft Communications:**
- Microsoft.windowscommunicationsapps (Mail & Calendar), Microsoft.Messaging, Microsoft.SkypeApp, Microsoft.YourPhone, Microsoft.549981C3F5F50 (Cortana)

**Microsoft Office:**
- Microsoft.MicrosoftOfficeHub, Microsoft.Office.OneNote, Microsoft.OutlookForWindows, Microsoft.M365Companions, Microsoft.PowerAutomateDesktop, Microsoft.Todos, Microsoft.Office.Sway

**Microsoft Media:**
- Microsoft.ZuneVideo (Movies & TV), Microsoft.ZuneMusic, Microsoft.Windows.Photos, Microsoft.3DBuilder, Microsoft.Microsoft3DViewer, Microsoft.MSPaint (Paint 3D)

**Microsoft Gaming:**
- Microsoft.XboxApp, Microsoft.XboxGameOverlay, Microsoft.GamingApp, Microsoft.XboxIdentityProvider, Microsoft.XboxSpeechToTextOverlay, Microsoft.Xbox.TCUI, Microsoft.XboxConsoleCompanion

**Microsoft Miscellaneous:**
- Microsoft.WindowsStore, MSTeams, MicrosoftTeams, Microsoft.MicrosoftSolitaireCollection, Microsoft.Whiteboard, Microsoft.Windows.DevHome, MicrosoftCorporationII.MicrosoftFamily, Microsoft.WindowsFeedbackHub, Microsoft.GetHelp, Microsoft.Getstarted, Microsoft.PCManager, Microsoft.MixedReality.Portal, Microsoft.RemoteDesktop, Microsoft.StartExperiencesApp (Widgets), Microsoft.NetworkSpeedTest, LinkedInforWindows

**Third-Party Consumer Apps:**
- Amazon.com.Amazon, Facebook, Instagram, Spotify, Netflix, Disney, TikTok, king.com.CandyCrushSaga, king.com.CandyCrushSodaSaga, king.com.BubbleWitch3Saga, AdobeSystemsIncorporated.AdobePhotoshopExpress, AutodeskSketchBook, Duolingo-LearnLanguagesforFree, PandoraMediaInc, Plex, TikTok, TuneInRadio, ACGMediaPlayer, BubbleWitch3Saga, CaesarsSlotsFreeCasino, COOKINGFEVER, DisneyMagicKingdoms, FarmVille2CountryEscape, Fitbit, Flipboard, HiddenCity, HULULLC.HULUPLUS, iHeartRadio, MarchofEmpires, Netflix, NYTCrossword, OneCalendar, PhototasticCollage, PicsArt-PhotoStudio, PolarrPhotoEditorAcademicEdition, PrimeVideo, Royal Revolt, Shazam, SlingTV, Spotify, TikTok, TuneInRadio, Twitter, Viber, WinZipUniversal, Wunderlist, Sidia.LiveWallpaper, EclipseManager, XING, ActiproSoftwareLLC, CyberLinkMediaSuiteEssentials, Microsoft.OneConnect, Asphal8Airborne

**OEM Apps:**
- AD2F1837.HPAIExperienceCenter, AD2F1837.HPConnectedMusic, AD2F1837.HPConnectedPhotopoweredbySnapfish, AD2F1837.HPDesktopSupportUtilities, AD2F1837.HPEasyClean, AD2F1837.HPFileViewer, AD2F1837.HPJumpStarts, AD2F1837.HPPCHardwareDiagnosticsWindows, AD2F1837.HPPowerManager, AD2F1837.HPPrinterControl, AD2F1837.HPPrivacySettings, AD2F1837.HPQuickDrop, AD2F1837.HPQuickTouch, AD2F1837.HPRegistration, AD2F1837.HPSupportAssistant, AD2F1837.HPSureShieldAI, AD2F1837.HPSystemInformation, AD2F1837.HPWelcome, AD2F1837.HPWorkWell, AD2F1837.myHP
- DellInc.DellDigitalDelivery, DellInc.DellMobileConnect, DellInc.DellSupportAssistforPCs
- E046963F.LenovoCompanion, LenovoCompanyLimited.LenovoVantageService

**Important protected apps (NOT included in presets — require strong warning):**
- Microsoft.WindowsStore, Microsoft.WindowsTerminal, Microsoft.GetHelp, Microsoft.WindowsAlarms, Microsoft.WindowsCalculator, Microsoft.WindowsNotepad — these are marked as protected in the preset logic, not removed by default

- [ ] **Step 2: Commit**

```bash
git add src/modules/tweaks/definitions/debloat.json
git commit -m "$(cat <<'EOF'
feat(tweaks): add debloat.json with 120+ appx removal entries

Covers: Bing Apps, System Utilities, Microsoft Communications,
Microsoft Office, Microsoft Media, Gaming, Third-Party, OEM apps.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: debloat_scanner.py — App Detection

**Files:**
- Create: `src/modules/debloat/debloat_scanner.py`

- [ ] **Step 1: Write debloat_scanner.py**

```python
"""debloat_scanner — detects installed bloatware apps and tweak states."""
import logging
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# All known package names from debloat.json
KNOWN_PACKAGES = {
    "Microsoft.BingWeather", "Microsoft.BingNews", "Microsoft.BingFinance",
    "Microsoft.BingSports", "Microsoft.BingTravel", "Microsoft.BingFoodAndDrink",
    "Microsoft.BingHealthAndFitness", "Microsoft.BingTranslator", "Microsoft.BingSearch",
    "Microsoft.WindowsCalculator", "Microsoft.WindowsCamera", "Microsoft.WindowsAlarms",
    "Microsoft.ScreenSketch", "Microsoft.WindowsNotepad", "Microsoft.Paint",
    "Microsoft.WindowsSoundRecorder", "MicrosoftCorporationII.QuickAssist",
    "Microsoft.MicrosoftStickyNotes", "Microsoft.WindowsTerminal",
    "Clipchamp.Clipchamp", "Microsoft.MicrosoftJournal",
    "Microsoft.windowscommunicationsapps", "Microsoft.Messaging",
    "Microsoft.SkypeApp", "Microsoft.YourPhone", "Microsoft.549981C3F5F50",
    "Microsoft.MicrosoftOfficeHub", "Microsoft.Office.OneNote",
    "Microsoft.OutlookForWindows", "Microsoft.M365Companions",
    "Microsoft.PowerAutomateDesktop", "Microsoft.Todos", "Microsoft.Office.Sway",
    "Microsoft.ZuneVideo", "Microsoft.ZuneMusic", "Microsoft.Windows.Photos",
    "Microsoft.3DBuilder", "Microsoft.Microsoft3DViewer", "Microsoft.MSPaint",
    "Microsoft.XboxApp", "Microsoft.XboxGameOverlay", "Microsoft.GamingApp",
    "Microsoft.XboxIdentityProvider", "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.Xbox.TCUI", "Microsoft.XboxConsoleCompanion",
    "Microsoft.WindowsStore", "MSTeams", "MicrosoftTeams",
    "Microsoft.MicrosoftSolitaireCollection", "Microsoft.Whiteboard",
    "Microsoft.Windows.DevHome", "MicrosoftCorporationII.MicrosoftFamily",
    "Microsoft.WindowsFeedbackHub", "Microsoft.GetHelp", "Microsoft.Getstarted",
    "Microsoft.PCManager", "Microsoft.MixedReality.Portal", "Microsoft.RemoteDesktop",
    "Microsoft.StartExperiencesApp", "Microsoft.NetworkSpeedTest",
    "LinkedInforWindows",
    "Amazon.com.Amazon", "Facebook", "Instagram", "Spotify", "Netflix",
    "Disney", "TikTok", "king.com.CandyCrushSaga", "king.com.CandyCrushSodaSaga",
    "king.com.BubbleWitch3Saga", "AdobeSystemsIncorporated.AdobePhotoshopExpress",
    "AutodeskSketchBook", "Duolingo-LearnLanguagesforFree", "PandoraMediaInc",
    "Plex", "TikTok", "TuneInRadio", "ACGMediaPlayer", "COOKINGFEVER",
    "DisneyMagicKingdoms", "FarmVille2CountryEscape", "Fitbit", "Flipboard",
    "HiddenCity", "HULULLC.HULUPLUS", "iHeartRadio", "MarchofEmpires",
    "NYTCrossword", "OneCalendar", "PhototasticCollage", "PicsArt-PhotoStudio",
    "PolarrPhotoEditorAcademicEdition", "PrimeVideo", "Royal Revolt", "Shazam",
    "SlingTV", "Twitter", "Viber", "WinZipUniversal", "Wunderlist",
    "Sidia.LiveWallpaper", "EclipseManager", "XING", "ActiproSoftwareLLC",
    "CyberLinkMediaSuiteEssentials", "Microsoft.OneConnect", "Asphalt8Airborne",
    "AD2F1837.HPAIExperienceCenter", "AD2F1837.HPConnectedMusic",
    "AD2F1837.HPConnectedPhotopoweredbySnapfish", "AD2F1837.HPDesktopSupportUtilities",
    "AD2F1837.HPEasyClean", "AD2F1837.HPFileViewer", "AD2F1837.HPJumpStarts",
    "AD2F1837.HPPCHardwareDiagnosticsWindows", "AD2F1837.HPPowerManager",
    "AD2F1837.HPPrinterControl", "AD2F1837.HPPrivacySettings", "AD2F1837.HPQuickDrop",
    "AD2F1837.HPQuickTouch", "AD2F1837.HPRegistration", "AD2F1837.HPSupportAssistant",
    "AD2F1837.HPSureShieldAI", "AD2F1837.HPSystemInformation", "AD2F1837.HPWelcome",
    "AD2F1837.HPWorkWell", "AD2F1837.myHP",
    "DellInc.DellDigitalDelivery", "DellInc.DellMobileConnect",
    "DellInc.DellSupportAssistforPCs",
    "E046963F.LenovoCompanion", "LenovoCompanyLimited.LenovoVantageService",
}


def get_installed_packages() -> Dict[str, str]:
    """Return {package_name: display_name} for all installed Appx packages."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-AppxPackage | Select-Object Name, PackageFullName | ConvertTo-Json -Compress"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    installed: Dict[str, str] = {}
    if not result.stdout.strip():
        return installed
    import json as _json
    try:
        data = _json.loads(result.stdout)
        if isinstance(data, dict):
            data = [data]
        for entry in data:
            name = entry.get("Name", "")
            if name in KNOWN_PACKAGES:
                installed[name] = name
    except Exception as e:
        logger.debug("Failed to parse AppxPackage output: %s", e)
    return installed


def check_app_installed(package_name: str) -> bool:
    """Return True if the given Appx package is installed."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-AppxPackage '{package_name}' -ErrorAction SilentlyContinue | Select-Object -First 1 Name"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return bool(result.stdout.strip())


# Apps that should be protected from accidental removal
PROTECTED_APPS = {
    "Microsoft.WindowsStore",
    "Microsoft.WindowsTerminal",
    "Microsoft.GetHelp",
    "Microsoft.WindowsAlarms",
    "Microsoft.WindowsCalculator",
    "Microsoft.WindowsNotepad",
}
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/debloat/debloat_scanner.py
git commit -m "$(cat <<'EOF'
feat(debloat): add debloat_scanner with app detection via Get-AppxPackage

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: debloat_module.py — BaseModule + 3-Tab UI

**Files:**
- Create: `src/modules/debloat/debloat_module.py`

- [ ] **Step 1: Write debloat_module.py skeleton**

```python
"""DebloatModule — bloatware removal, privacy hardening, AI feature disabling."""
import logging
import subprocess
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QGridLayout, QGroupBox,
    QHeaderView, QLabel, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QStyle, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QMessageBox,
)
from PyQt6.QtGui import QColor

from core.base_module import BaseModule
from core.backup_service import BackupService
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider
from core.worker import Worker
from modules.debloat.debloat_scanner import get_installed_packages, PROTECTED_APPS
from modules.tweaks.tweak_engine import TweakEngine

logger = logging.getLogger(__name__)

_PROTECTED_REASONS = {
    "Microsoft.WindowsStore": "Required for installing apps from Microsoft Store",
    "Microsoft.WindowsTerminal": "Recommended terminal — removal not advised",
    "Microsoft.GetHelp": "Built-in Windows help system",
    "Microsoft.WindowsAlarms": "System clock and alarms",
    "Microsoft.WindowsCalculator": "System calculator",
    "Microsoft.WindowsNotepad": "System text editor",
}

_DEBOOT_DEFINITIONS = {
    "bing": "bing_weather", "gaming": "xbox_gaming_overlay",
    "office": "microsoft_office_hub", "media": "zune_music",
}


class _TweakTableWidget(QWidget):
    """Reusable table widget for tweak/app rows."""

    def __init__(self, columns: List[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget()
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._layout.addWidget(self._table)

    def table(self) -> QTableWidget:
        return self._table

    def add_row(self, data: List[str], key: Optional[str] = None) -> int:
        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, text in enumerate(data):
            self._table.setItem(row, col, QTableWidgetItem(text))
        if key:
            self._table.item(row, 0).setData(Qt.ItemDataRole.UserRole, key)
        return row

    def clear_rows(self) -> None:
        self._table.setRowCount(0)


class DebloatModule(BaseModule):
    name = "Debloat"
    icon = "\u26a1"
    description = "Remove bloatware, disable telemetry, and harden privacy"
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._engine: Optional[TweakEngine] = None
        self._tab_widget: Optional[QWidget] = None

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(4, 4, 4, 4)

        from PyQt6.QtWidgets import QTabWidget
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3c3c3c; border-radius: 4px; background: #252525; }
            QTabBar::tab { background: #2d2d2d; color: #b0b0b0; padding: 6px 12px; margin-right: 2px; border: 1px solid #3c3c3c; border-bottom: none; border-radius: 4px 4px 0 0; }
            QTabBar::tab:selected { background: #252525; color: #e0e0e0; font-weight: bold; }
            QTabBar::tab:hover { background: #3c3c3c; }
        """)

        self._apps_tab = self._build_apps_tab()
        self._privacy_tab = self._build_tweaks_tab(["privacy.json", "telemetry.json", "services.json", "network.json"])
        self._ai_tab = self._build_tweaks_tab(["ai_features.json", "navigation.json"])

        self._tab_widget.addTab(self._apps_tab, "Apps")
        self._tab_widget.addTab(self._privacy_tab, "Privacy & Telemetry")
        self._tab_widget.addTab(self._ai_tab, "AI & Navigation")

        layout.addWidget(self._tab_widget)
        return self._widget

    def _build_apps_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._apps_status = QLabel("Click 'Scan Apps' to detect installed bloatware")
        self._apps_status.setStyleSheet("font-size: 13px; padding: 4px; color: #b0b0b0;")
        layout.addWidget(self._apps_status)

        btn_layout = QGridLayout()
        self._scan_apps_btn = QPushButton("Scan Apps")
        self._scan_apps_btn.clicked.connect(self._on_scan_apps)
        self._apply_selected_btn = QPushButton("Apply Selected")
        self._apply_selected_btn.clicked.connect(self._on_apply_selected_apps)
        self._apply_selected_btn.setEnabled(False)
        self._apply_all_btn = QPushButton("Apply All Safe")
        self._apply_all_btn.clicked.connect(self._on_apply_all_safe_apps)
        self._apply_all_btn.setEnabled(False)
        btn_layout.addWidget(self._scan_apps_btn, 0, 0)
        btn_layout.addWidget(self._apply_selected_btn, 0, 1)
        btn_layout.addWidget(self._apply_all_btn, 0, 2)
        layout.addLayout(btn_layout)

        self._apps_progress = QProgressBar()
        self._apps_progress.setVisible(False)
        layout.addWidget(self._apps_progress)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self._apps_table = QTableWidget()
        self._apps_table.setColumnCount(4)
        self._apps_table.setHorizontalHeaderLabels(["\u2610", "App Name", "Category", "Status"])
        self._apps_table.horizontalHeader().setStretchLastSection(True)
        self._apps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._apps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._apps_table.itemChanged.connect(self._on_apps_item_changed)
        table_layout.addWidget(self._apps_table)

        scroll.setWidget(table_widget)
        layout.addWidget(scroll)
        return widget

    def _build_tweaks_tab(self, json_files: List[str]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        status_lbl = QLabel("Loading tweak definitions...")
        status_lbl.setStyleSheet("font-size: 13px; padding: 4px;")
        layout.addWidget(status_lbl)

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["\u2610", "Tweak", "Category", "Risk", "Status"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(table)

        preset_layout = QGridLayout()
        light_btn = QPushButton("Light Debloat")
        full_btn = QPushButton("Full Debloat")
        privacy_btn = QPushButton("Privacy-Focused")
        custom_btn = QPushButton("Custom")
        preset_layout.addWidget(light_btn, 0, 0)
        preset_layout.addWidget(full_btn, 0, 1)
        preset_layout.addWidget(privacy_btn, 0, 2)
        preset_layout.addWidget(custom_btn, 0, 3)
        layout.addLayout(preset_layout)

        apply_btn = QPushButton("Apply Selected Tweaks")
        layout.addWidget(apply_btn)

        return widget

    def on_start(self, app) -> None:
        self.app = app
        backup = BackupService(app._app_data_dir)
        self._engine = TweakEngine(backup)

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def get_refresh_interval(self) -> Optional[int]:
        return None

    # ------------------------------------------------------------------
    # Apps tab
    # ------------------------------------------------------------------

    def _on_scan_apps(self) -> None:
        self._scan_apps_btn.setEnabled(False)
        self._apps_status.setText("Scanning installed apps...")
        w = Worker(self._do_scan_apps)
        w.signals.result.connect(self._on_apps_scanned)
        w.signals.error.connect(self._on_scan_error)
        self._workers.append(w)
        self.app.thread_pool.start(w)

    def _do_scan_apps(self, worker) -> Dict[str, List[str]]:
        installed = get_installed_packages()
        return {"installed": list(installed.keys())}

    def _on_apps_scanned(self, result: Dict) -> None:
        self._scan_apps_btn.setEnabled(True)
        installed: List[str] = result.get("installed", [])
        self._apps_status.setText(f"Scan complete — {len(installed)} bloatware apps detected")
        self._populate_apps_table(installed)
        self._apply_selected_btn.setEnabled(len(installed) > 0)
        self._apply_all_btn.setEnabled(len(installed) > 0)

    def _populate_apps_table(self, installed: List[str]) -> None:
        self._apps_table.setRowCount(0)
        self._installed_apps = installed

        from modules.tweaks.tweak_engine import TweakEngine
        import os, json
        base = os.path.join(os.path.dirname(__file__), "..", "tweaks", "definitions", "debloat.json")
        entries = []
        if os.path.exists(base):
            with open(base, encoding="utf-8") as f:
                entries = json.load(f)

        for entry in entries:
            pkg = entry.get("package", "")
            if pkg not in installed:
                continue
            row = self._apps_table.rowCount()
            self._apps_table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.CheckState.Unchecked)
            self._apps_table.setItem(row, 0, chk)
            self._apps_table.setItem(row, 1, QTableWidgetItem(entry.get("name", pkg)))
            self._apps_table.setItem(row, 2, QTableWidgetItem(entry.get("category", "")))
            self._apps_table.setItem(row, 3, QTableWidgetItem("\u25cf Present"))
            self._apps_table.item(row, 3).setData(Qt.ItemDataRole.UserRole, entry.get("id", ""))
            if pkg in PROTECTED_APPS:
                self._apps_table.item(row, 3).setForeground(QColor("#ff8800"))

    def _on_apps_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            checked = sum(
                1 for r in range(self._apps_table.rowCount())
                if self._apps_table.item(r, 0).checkState() == Qt.CheckState.Checked
            )
            self._apply_selected_btn.setEnabled(checked > 0)

    def _on_apply_selected_apps(self) -> None:
        selected = []
        for r in range(self._apps_table.rowCount()):
            if self._apps_table.item(r, 0).checkState() == Qt.CheckState.Checked:
                entry_id = self._apps_table.item(r, 3).data(Qt.ItemDataRole.UserRole)
                pkg = self._find_package_by_id(entry_id)
                if pkg in PROTECTED_APPS:
                    msg = _PROTECTED_REASONS.get(pkg, "This app may be required for system functionality.")
                    reply = QMessageBox.warning(
                        self._widget, "Protected App",
                        f"{msg}\n\nRemove anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        continue
                selected.append(entry_id)
        if selected:
            self._do_apply_apps(selected)

    def _on_apply_all_safe_apps(self) -> None:
        selected = []
        for r in range(self._apps_table.rowCount()):
            entry_id = self._apps_table.item(r, 3).data(Qt.ItemDataRole.UserRole)
            pkg = self._find_package_by_id(entry_id)
            if pkg not in PROTECTED_APPS:
                selected.append(entry_id)
        if selected:
            self._do_apply_apps(selected)

    def _do_apply_apps(self, entry_ids: List[str]) -> None:
        self._apply_selected_btn.setEnabled(False)
        self._apply_all_btn.setEnabled(False)
        self._apps_progress.setVisible(True)
        self._apps_progress.setRange(0, len(entry_ids))
        self._apps_progress.setValue(0)

        def work(w: Worker):
            from modules.tweaks.tweak_engine import TweakEngine
            from core.backup_service import BackupService
            import os, json, datetime
            backup = BackupService(self.app._app_data_dir)
            engine = TweakEngine(backup)
            rp_id = f"debloat_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup.create_restore_point(rp_id)

            base = os.path.join(os.path.dirname(__file__), "..", "tweaks", "definitions", "debloat.json")
            with open(base, encoding="utf-8") as f:
                all_entries = {e["id"]: e for e in json.load(f)}

            success = 0
            for i, eid in enumerate(entry_ids):
                if w.is_cancelled:
                    return {"success": success, "total": len(entry_ids)}
                entry = all_entries.get(eid)
                if entry:
                    engine.apply_tweak(entry, rp_id)
                    success += 1
                w.signals.progress.emit(i + 1)
            return {"success": success, "total": len(entry_ids)}

        w = Worker(work)
        w.signals.progress.connect(self._apps_progress.setValue)
        w.signals.result.connect(self._on_apps_applied)
        w.signals.error.connect(self._on_apply_error)
        self._workers.append(w)
        self.app.thread_pool.start(w)

    def _on_apps_applied(self, result: Dict) -> None:
        self._apps_progress.setVisible(False)
        self._apply_selected_btn.setEnabled(True)
        self._apply_all_btn.setEnabled(True)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self._widget, "Debloat Complete",
            f"Successfully removed {result['success']} of {result['total']} apps.\n"
            f"A restore point has been created.",
        )
        self._on_scan_apps()

    def _on_scan_error(self, err: str) -> None:
        self._scan_apps_btn.setEnabled(True)
        self._apps_status.setText(f"Scan failed: {err}")
        logger.error("Debloat scan error: %s", err)

    def _on_apply_error(self, err: str) -> None:
        self._apps_progress.setVisible(False)
        self._apply_selected_btn.setEnabled(True)
        self._apply_all_btn.setEnabled(True)
        logger.error("Debloat apply error: %s", err)

    def _find_package_by_id(self, entry_id: str) -> str:
        import os, json
        base = os.path.join(os.path.dirname(__file__), "..", "tweaks", "definitions", "debloat.json")
        if os.path.exists(base):
            with open(base, encoding="utf-8") as f:
                for entry in json.load(f):
                    if entry.get("id") == entry_id:
                        return entry.get("package", "")
        return ""

    def get_search_provider(self) -> Optional[SearchProvider]:
        return None
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/debloat/debloat_module.py
git commit -m "$(cat <<'EOF'
feat(debloat): add DebloatModule with Apps tab UI and scan/remove flow

Apps tab: detects installed bloatware via Get-AppxPackage,
shows table with checkboxes, Apply Selected, Apply All Safe.
Protected apps (Store, Terminal, Get Help) require confirmation.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Register DebloatModule in main.py

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Register the module**

Add to `src/main.py`:
```python
from modules.debloat.debloat_module import DebloatModule
app.module_registry.register(DebloatModule())
```

Insert after the existing module registrations (near the cleanup/performance modules).

- [ ] **Step 2: Syntax check**

Run: `python -c "import sys; sys.path.insert(0, 'src'); import main; print('OK')"`

Expected output: `OK` (no errors)

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "$(cat <<'EOF'
feat: register DebloatModule in module registry

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Add Preset Profiles to preset_manager.py

**Files:**
- Modify: `src/modules/tweaks/preset_manager.py`

- [ ] **Step 1: Add debloat presets to builtins directory**

Create `src/modules/tweaks/definitions/builtins/debloat_light.json`, `debloat_full.json`, `debloat_privacy.json`, `debloat_custom.json` in the builtins directory.

`debloat_light.json`:
```json
{
  "name": "Light Debloat",
  "version": 1,
  "builtin": true,
  "description": "Remove Bing apps, Xbox gaming bloat, Solitaire, Clipchamp — safe for all users",
  "tweaks": {
    "Bing Apps": ["remove_bing_weather", "remove_bing_news", "remove_bing_sports", "remove_bing_finance", "remove_bing_travel"],
    "Gaming": ["remove_xbox_gaming_overlay", "remove_xbox_app"],
    "Media": ["remove_clipchamp", "remove_solitaire"]
  }
}
```

`debloat_full.json`:
```json
{
  "name": "Full Debloat",
  "version": 1,
  "builtin": true,
  "description": "Remove all 120+ bloatware apps except protected system apps (Store, Terminal, Get Help, Calculator, Notepad, Alarms)",
  "tweaks": {
    "System Utilities": ["remove_*_EXCEPT_store_*"],
    "Bing Apps": ["remove_*"],
    "Gaming": ["remove_*"],
    "Media": ["remove_*"],
    "Microsoft Communications": ["remove_*"],
    "Third-Party": ["remove_*"],
    "OEM": ["remove_*"]
  },
  "apps": {"remove": ["all_except_protected"]}
}
```

`debloat_privacy.json`:
```json
{
  "name": "Privacy-Focused",
  "version": 1,
  "builtin": true,
  "description": "Keep all apps but apply all privacy, telemetry, AI feature, and navigation pane tweaks",
  "tweaks": {
    "Privacy": ["*"],
    "Telemetry": ["*"],
    "Services": ["disable_delivery_optimization", "disable_diagtrack"],
    "AI Features": ["*"],
    "Navigation Pane": ["*"]
  }
}
```

`debloat_custom.json`:
```json
{
  "name": "Custom Debloat",
  "version": 1,
  "builtin": true,
  "description": "User-configurable — select individual apps and tweaks manually",
  "tweaks": {}
}
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/tweaks/definitions/builtins/
git commit -m "$(cat <<'EOF'
feat(presets): add 4 debloat preset profiles

Light Debloat, Full Debloat, Privacy-Focused, Custom.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Build and Smoke Test

**Files:**
- Test: `docs/superpowers/plans/2026-04-11-windows-debloat-design.md`

- [ ] **Step 1: Syntax check**

Run: `python -c "import sys; sys.path.insert(0, 'src'); import main; print('OK')"`

Expected: `OK`

- [ ] **Step 2: Build portable exe**

Run: `pyinstaller WinClientTool-portable.spec -y --distpath dist`

Expected: `dist/WinClientTool-Portable.exe` created without errors

- [ ] **Step 3: Smoke test — run app and navigate to Debloat module**

Launch the exe. Navigate to Debloat module. Click "Scan Apps". Verify no crashes in the console.

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| 120+ app removal definitions | Task 3 (debloat.json) |
| Apps tab with scan/detect | Task 4 (scanner) + Task 5 (module) |
| Privacy & telemetry tab | Task 5 (_build_tweaks_tab) |
| AI & navigation tab | Task 5 (_build_tweaks_tab) |
| One-click preset profiles | Task 7 (presets) + Task 5 (preset buttons) |
| `_apply_scheduled_task()` | Task 1 (TweakEngine) |
| `detect_status()` for appx | Task 1 (TweakEngine) |
| TweakEngine CREATE_NO_WINDOW on appx | Task 1 |
| ai_features.json (5 entries) | Task 2 |
| navigation.json (4 entries) | Task 2 |
| Register module in main.py | Task 6 |
| Restore point before apply | Task 5 (_do_apply_apps) |
| Protected app confirmation dialog | Task 5 (_on_apply_selected_apps) |

---

## Type Consistency Check

- `TweakEngine.apply_tweak(tweak, rp_id, on_error)` — called in Task 5 with `entry` dict from debloat.json, all fields match
- `BackupService.create_restore_point(rp_id)` — called at start of `_do_apply_apps` in Task 5
- `Worker(do_work)` pattern — `worker` parameter named consistently throughout Task 5
- `worker.is_cancelled` property (not method) — used in `_do_apply_apps` in Task 5
- `w.signals.progress.emit(int)` — used in `_do_apply_apps` in Task 5
- `self._workers.append(w)` — workers tracked in every Worker start in Task 5
- `subprocess.CREATE_NO_WINDOW` — used in all subprocess calls in Tasks 1 and 4
- `QMessageBox` — used for protected app confirmation in Task 5
