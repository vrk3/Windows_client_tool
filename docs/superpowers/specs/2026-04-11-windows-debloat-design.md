# Design: Windows Debloat Module

## Context

The app has 40+ modules covering cleanup, performance tuning, registry tweaks, and diagnostics. It is missing a unified debloating interface that ties together app removal, privacy hardening, and AI feature disabling. Win11Debloat, CCleaner, privacy.sexy, and PatchMyPC are the reference implementations.

**Research sources:**
- [Win11Debloat GitHub Wiki — App Removal](https://github.com/Raphire/Win11Debloat/wiki/App-Removal) — 120+ removable apps with exact `Get-AppxPackage` package names across 8 categories
- [Win11Debloat GitHub Wiki — Features](https://github.com/Raphire/Win11Debloat/wiki/Features) — full registry/script tweak catalogue
- [PatchMyPC — Remove Built-In Windows Apps](https://patchmypc.com/blog/remove-built-windows-apps-powershell/) — bloatware removal reference
- CCleaner, privacy.sexy, Tiny11Builder — known approaches

The existing codebase already covers most registry/service tweaks. This module adds a structured debloat UI and fills the remaining gaps.

---

## Architecture

```
debloat_module.py              — BaseModule entry, 3-tab widget
debloat_scanner.py            — detects installed bloatware (Get-AppxPackage), 
                                  checks tweak states (registry/service/scheduled task)
tweak_engine.py              — unchanged; add _apply_scheduled_task() for DISABLE-ScheduledTask
backup_service.py            — unchanged
definitions/debloat.json      — new: bloatware app removal definitions (appx step type)
definitions/ai_features.json  — new: Win11 24H2 AI feature tweaks beyond existing privacy.json
definitions/navigation.json  — new: File Explorer navigation pane tweaks
```

---

## 1. New Tweak Step Type: `appx`

Extend `TweakEngine` with `_apply_appx()` and `_revert_appx()`. Existing `tweak_engine.py` already has `_apply_appx()` that calls `Get-AppxPackage | Remove-AppxPackage`. Add `_apply_scheduled_task()` for the DISABLE-ScheduledTask operation:

```python
elif step_type == "appx":
    return self._apply_appx(step, rp_id)
elif step_type == "scheduled_task":
    return self._apply_scheduled_task(step, rp_id)

def _apply_scheduled_task(self, step: Dict, rp_id: str) -> Optional[StepRecord]:
    task_name = step["task_name"]  # e.g. "Microsoft\\Windows\\Feedback\\Siuf\\DmClient"
    current = self._get_scheduled_task_state(task_name)  # "Enabled" or "Disabled"
    subprocess.run(["schtasks", "/change", "/tn", task_name, "/disable"],
                   creationflags=CREATE_NO_WINDOW, check=True)
    return StepRecord("scheduled_task", task_name, current, "Disabled")
```

App removal uses the existing `appx` step type which is already implemented:
```json
{"type": "appx", "package": "Microsoft.BingWeather", "action": "remove"}
{"type": "appx", "package": "Microsoft.XboxGamingOverlay", "action": "remove"}
```

**App detection** (`debloat_scanner.detect_installed_apps()`): run `Get-AppxPackage | Select-Object Name, PackageFullName` via PowerShell subprocess and match against the known package list.

---

## 2. New Tweak Definition Files

### `definitions/debloat.json`

120+ entries across 8 categories. Example entry structure:

```json
{
  "id": "remove_bing_weather",
  "name": "Bing Weather",
  "description": "Weather app with ad-powered news feed.",
  "category": "Bing Apps", "risk": "low", "requires_admin": true,
  "package": "Microsoft.BingWeather",
  "steps": [{"type": "appx", "package": "Microsoft.BingWeather", "action": "remove"}]
}
```

Full category list (from Win11Debloat):

| Category | Apps |
|----------|------|
| System Utilities | Calculator, Camera, Clock, Alarms, Snipping Tool, Notepad, Paint, Screen Sketch, Sound Recorder, Quick Assist, Sticky Notes, Windows Terminal, Clipchamp |
| Microsoft Communications | Mail & Calendar, Messaging, Skype UWP, Your Phone/Phone Link, Cortana |
| Microsoft Office | Office Hub, OneNote, Outlook for Windows, Microsoft 365 Companions, Power Automate, To Do, Sway |
| Microsoft Media | Movies & TV, Zune Music (Media Player), Photos, 3D Builder, 3D Viewer, Paint 3D |
| Microsoft News & Finance | Bing Weather, Bing News, Bing Finance, Bing Sports, Bing Travel, Bing Food & Drink, Bing Health & Fitness, Bing Translator, Bing Search |
| Microsoft Gaming | Xbox App, Xbox Game Overlay, Xbox Gaming App, Xbox Identity Provider, Xbox Speech-to-Text, Xbox TCUI, Xbox Console Companion |
| Microsoft Miscellaneous | Microsoft Store, Microsoft Teams (new + old), Microsoft Solitaire Collection, Microsoft Journal, Whiteboard, Dev Home, Family Safety, Microsoft News, Feedback Hub, Get Help, Get Started, Microsoft PC Manager, Mixed Reality Portal, Remote Desktop, Widgets, Network Speed Test, LinkedIn |
| Third-Party | Amazon, Facebook, Instagram, Spotify, Netflix, Disney, TikTok, Spotify, Candy Crush, Duolingo, Skype UWP, and 50+ more |

**OEM apps**: HP AI Experience Center, HP Connected Music, Dell SupportAssist, Lenovo Vantage — detected by OEM brand registry keys.

**Safety**: All Microsoft system apps marked `risk: low`. Third-party and OEM apps marked `risk: low`. Apps that break functionality (Get Help, Microsoft Store, Windows Terminal) marked with strong warnings and NOT included in preset profiles.

### `definitions/ai_features.json`

New Win11 24H2 AI features beyond existing `win11_recall_disable` and `win11_copilot_disable`:

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
    "description": "Disables Microsoft Copilot integration in Microsoft Edge browser.",
    "category": "AI Features", "risk": "low", "requires_admin": false,
    "steps": [
      {"type": "registry", "key": "HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge", "value": "Sidebar", "data": 0, "kind": "DWORD"},
      {"type": "registry", "key": "HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge", "value": "MicrosoftEdgeShowSidebarFactoryApp", "data": 0, "kind": "DWORD"}
    ]
  },
  {
    "id": "disable_paint_copilot",
    "name": "Disable AI in Paint",
    "description": "Disables the Cocreator AI image generation feature in Paint.",
    "category": "AI Features", "risk": "low", "requires_admin": false,
    "steps": [{"type": "registry", "key": "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Applets\\Paint\\Settings", "value": "DisableAIFeatures", "data": 1, "kind": "DWORD"}]
  }
]
```

### `definitions/navigation.json`

File Explorer navigation pane tweaks not yet in `ui_tweaks.json`:

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
    "steps": [{"type": "command", "cmd": "powershell -Command \"Remove-Item -Path 'HKCU:\\Software\\Classes\\CLSID\\{262榴7A5-3AD3-4D50-B4D4-A1F6B0D5C89E}' -Recurse -Force -ErrorAction SilentlyContinue\""}]
  },
  {
    "id": "disable_drive_definitions",
    "name": "Hide Duplicate Drive Letters",
    "description": "Removes duplicate drive letter entries from the File Explorer navigation pane.",
    "category": "Navigation Pane", "risk": "low", "requires_admin": false,
    "steps": [{"type": "registry", "key": "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer", "value": "HideDriveLettersWithoutNetDrive", "data": 1, "kind": "DWORD"}]
  }
]
```

---

## 3. DebloatModule UI (Option A — PerfTuner-style Table)

**UI Pattern**: Like `PerfTunerModule`, a `QTableWidget` with one row per tweak/app, 5 columns: ☑ Select | Name | Category | Risk | Status. Per-row `Apply` button. Preset profile buttons at top. Progress bar during apply.

```
┌─────────────────────────────────────────────────────────────────┐
│ Windows Debloat                                    [Preset ▾]   │
│                                                                   │
│  [Light]  [Full]  [Privacy-Focused]  [Custom]                     │
│                                                                   │
│  ☑  Name                    │ Category       │ Risk  │ Status    │
│  ──────────────────────────────────────────────────────────────    │
│  ☑  Bing Weather            │ Bing Apps      │ Low   │ ● Present │
│  ☑  Xbox Gaming Overlay     │ Gaming         │ Low   │ ● Present │
│  ☐  Microsoft Store         │ System         │ High  │ ● Present │
│  ☐  Clipchamp               │ Media          │ Low   │ ● Present │
│  ...                                                          ▼  │
│                                                                   │
│  [Scan Apps]              [Apply Selected]  [Apply All Safe]     │
└─────────────────────────────────────────────────────────────────┘
```

**Three tabs**: Apps | Privacy & Telemetry | AI & Navigation

- **Apps tab**: `debloat_scanner.detect_installed_apps()` populates the table. Shows installed bloatware. "Scan" re-detects. "Apply Selected" removes checked apps.
- **Privacy & Telemetry tab**: Shows existing tweak definitions from `telemetry.json`, `privacy.json`, `services.json`, `network.json` — uses `TweakEngine.get_tweak_state()` to show current status. Filtered to show only debloat-relevant tweaks.
- **AI & Navigation tab**: `ai_features.json` + `navigation.json` tweaks.

**Preset profiles** — `preset_manager.py` extends with new presets:
- **Light debloat**: removes only Bing Apps + Xbox Gaming + Solitaire + Clipchamp (advertising/leisure)
- **Full debloat**: removes all 120+ removable apps except Store, Terminal, Get Help, Alarms, Calculator, Notepad, Snipping Tool (functional requirements)
- **Privacy-focused**: keeps apps but applies all privacy telemetry tweaks + disables Recall/Copilot/Click-to-Do

**State detection**:
- Apps: `Get-AppxPackage` query
- Registry tweaks: read current registry value and compare to target
- Service tweaks: query service `StartType` via `sc qc`
- Scheduled tasks: `schtasks /query /tn "taskname" /fo LIST` check

**Apply flow**:
1. User selects apps/tweaks, clicks "Apply Selected"
2. `BackupService.create_restore_point()` — creates restore point first
3. `TweakEngine.apply_tweak()` — applies each step with `on_error` callback
4. UI updates status column to "Applied" or "Failed"
5. Toast notification: "X of Y tweaks applied"

**Revert**: `BackupService.restore(rp_id)` + refresh UI to pre-apply state.

**Confirmation**: before removing system apps (Store, Terminal, Get Help), show `QMessageBox.warning` with "This app is required for [reason]. Remove anyway?"

---

## 4. Gaps Analysis

| Gap | Status | Action |
|-----|--------|--------|
| Recall, Copilot disable | Done (privacy.json) | No change |
| Click To Do, AI Hub disable | Missing | Add to `ai_features.json` |
| WSAIFabricSvc service | Missing | Add to `ai_features.json` |
| Scheduled task DISABLE | TweakEngine doesn't have it | Add `_apply_scheduled_task()` to TweakEngine |
| Nav pane: Gallery, 3D Objects, Home | Missing | Add to `navigation.json` |
| Delivery Optimization user cache | Already in cleanup_scanner | No change |
| Storage Sense config | Missing | Add to `performance.json` |
| Windows Update deferral policies | Partial (services.json has wuauserv manual) | Add deferral period / notification settings |
| 120+ app removal | No JSON definitions | Create `debloat.json` |

---

## 5. Files to Create/Modify

### New files
- `src/modules/debloat/debloat_module.py` — BaseModule, 3-tab UI
- `src/modules/debloat/debloat_scanner.py` — app detection, state detection
- `src/modules/debloat/__init__.py`
- `src/modules/debloat/debloat_search_provider.py`
- `src/modules/tweaks/definitions/debloat.json` — 120+ appx removal entries
- `src/modules/tweaks/definitions/ai_features.json` — 5 new AI entries
- `src/modules/tweaks/definitions/navigation.json` — 4 nav pane entries

### Modify files
- `src/modules/tweaks/tweak_engine.py` — add `_apply_scheduled_task()`, add `get_tweak_state()`
- `src/modules/tweaks/preset_manager.py` — add 4 debloat presets
- `src/main.py` — register `DebloatModule`

---

## Edge Cases

- **App already removed**: `Get-AppxPackage` returns empty — mark as "Not installed" in status column, disable Apply button
- **Store app removal blocked**: Some apps are protected — `Remove-AppxPackage` fails with `Access is denied`; catch and show error in status
- **Non-admin user**: Apps tab requires admin (appx removal needs elevation); show banner if not elevated
- **Restore point on failure**: If apply partially fails, still save the restore point with successful steps
- **Win10 vs Win11**: Some AI features (Recall, Click-to-Do, AI Hub) are Win11 24H2 only — detect OS version and hide inapplicable rows
- **OEM machines**: HP/Dell/Lenovo apps only appear on OEM systems — detection already accounts for this via `Get-AppxPackage`
