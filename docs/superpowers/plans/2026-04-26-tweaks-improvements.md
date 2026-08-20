# Tweaks Module Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add search/filter, revert/undo UI, restart-required indicators, and per-tweak details to the Tweaks module.

**Architecture:**
- `TweakRow` gets a search-highlight mechanism via a filter callback passed from `TweakTab`
- `TweakTab` gets a `QLineEdit` filter bar that calls `_filter_tweaks()` to hide/show rows by name/description
- A new `_RevertDialog` (QDialog) lists sessions from `BackupService.list_restore_points()` and calls `restore_point()`
- Status labels get a 🔄 suffix for tweaks with `requires_restart: true` or that modify services
- A new `_TweakDetailsDialog` (QDialog) shows all steps with before/after values and impact description
- A bottom bar "Revert Session" button opens the dialog
- Keyboard shortcuts via `QShortcut` in the tab widget

**Tech Stack:** Python 3.12, PyQt6, sqlite3 (existing BackupService)

---

## File Changes

| File | Action |
|---|---|
| `src/modules/tweaks/tweaks_module.py` | Add search bar, revert button, details dialog, restart indicator, keyboard shortcuts |
| `src/modules/tweaks/tweak_engine.py` | Add `requires_restart()` method to TweakEngine |
| `src/modules/tweaks/definitions/privacy.json` | Add `"requires_restart": false` to all entries (no change needed — default false) |
| `src/modules/tweaks/definitions/services.json` | Add `"requires_restart": true` to service-step tweaks |

---

## Task 1: Add search/filter bar to TweakTab

**Files:**
- Modify: `src/modules/tweaks/tweaks_module.py`

TweakTab gets a `QLineEdit` filter bar at the top. When text changes, it calls `_apply_filter(text)` which shows/hides rows based on name or description matching (case-insensitive). Rows that don't match are hidden, not removed from layout.

- [ ] **Step 1: Add `_filter_bar` and `_filter_edit` to TweakTab.__init__**

In `TweakTab.__init__`, add a filter bar at the top of the layout, before the scroll area:

```python
# Add to TweakTab.__init__ after self._rows setup:
filter_layout = QHBoxLayout()
filter_layout.setContentsMargins(0, 0, 0, 4)
self._filter_edit = QLineEdit()
self._filter_edit.setPlaceholderText("Filter tweaks… (Ctrl+F)")
self._filter_edit.textChanged.connect(self._apply_filter)
filter_layout.addWidget(self._filter_edit)
clear_btn = QPushButton("✕")
clear_btn.setFixedWidth(30)
clear_btn.setFlat(True)
clear_btn.clicked.connect(lambda: self._filter_edit.setText(""))
filter_layout.addWidget(clear_btn)
```

- [ ] **Step 2: Insert filter_layout at top of TweakTab layout**

In `TweakTab.__init__`, the layout is built with `QVBoxLayout(self)`. After the layout is created, insert the filter bar at position 0:

```python
layout.insertLayout(0, filter_layout)
```

- [ ] **Step 3: Add `_apply_filter` method to TweakTab**

```python
def _apply_filter(self, text: str) -> None:
    """Show/hide rows based on filter text (case-insensitive name or description match)."""
    text_lower = text.lower().strip()
    for tweak_id, row in self._rows.items():
        if not text_lower:
            row.show()
            continue
        name_match = text_lower in tweak_id.lower() or text_lower in tweak_id.replace("_", " ").lower()
        desc_match = text_lower in tweak.get("description", "").lower()
        if name_match or desc_match:
            row.show()
        else:
            row.hide()
```

- [ ] **Step 4: Add import for QLineEdit and QPushButton if not present**

Check existing imports — `QLineEdit` is not in the current import block. Add `QLineEdit` to the `QWidget` import.

- [ ] **Step 5: Test by running syntax check**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.tweaks import tweaks_module as tm; print('OK')"`

---

## Task 2: Add requires_restart detection to TweakEngine

**Files:**
- Modify: `src/modules/tweaks/tweak_engine.py`

- [ ] **Step 1: Add `requires_restart()` method to TweakEngine**

Add after `detect_status()`:

```python
def requires_restart(self, tweak: Dict) -> bool:
    """Return True if applying this tweak requires a Windows restart to take effect."""
    steps = tweak.get("steps", [])
    if not steps:
        return False
    # Service start_type changes always need a restart
    for step in steps:
        if step.get("type") == "service":
            return True
        # Registry changes to certain keys known to need restart
        key = step.get("key", "")
        restart_keys = [
            r"HKLM\SYSTEM\CurrentControlSet\Services",
            r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
            r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
        ]
        if step.get("type") == "registry":
            for rk in restart_keys:
                if key.startswith(rk):
                    return True
    return False
```

- [ ] **Step 2: Update TweaksModule._detect_statuses to also send requires_restart signal**

Add a new signal `_tweak_restart_required = pyqtSignal(str, bool)` to `_Signals` class, then in `_detect_statuses`, also emit whether each tweak requires restart.

In `_Signals` class (line ~40), add:
```python
tweak_restart_required = pyqtSignal(str, bool)  # tweak_id, requires_restart
```

In `_detect_statuses` worker:
```python
requires_restart = self._engine.requires_restart(tweak)
self._signals.tweak_restart_required.emit(tweak["id"], requires_restart)
```

Add handler in `create_widget` after other signal connections:
```python
self._signals.tweak_restart_required.connect(self._on_restart_required)
```

Add `_on_restart_required` method:
```python
def _on_restart_required(self, tweak_id: str, required: bool) -> None:
    for tab in self._tab_widgets.values():
        if tweak_id in tab._rows:
            tab._rows[tweak_id].set_restart_required(required)
```

- [ ] **Step 3: Add `set_restart_required` to TweakRow**

Add `self._requires_restart = False` to `__init__`, and add:

```python
def set_restart_required(self, required: bool) -> None:
    self._requires_restart = required
    self._update_status_style()

def _update_status_style(self) -> None:
    # Add subtle styling for restart-required tweaks
    if self._requires_restart:
        self.status_label.setToolTip("Requires Windows restart to take effect")
```

Update `set_status` to check `self._requires_restart` and append 🔄 to the status text if needed.

- [ ] **Step 4: Test syntax check**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.tweaks.tweak_engine import TweakEngine; print('OK')"`

---

## Task 3: Add Revert Session dialog

**Files:**
- Modify: `src/modules/tweaks/tweaks_module.py`

- [ ] **Step 1: Add `RevertDialog` class before TweaksModule**

```python
class RevertDialog(QDialog):
    """Dialog listing restore points so user can revert a tweak session."""

    def __init__(self, backup_service, parent=None):
        super().__init__(parent)
        self._backup = backup_service
        self.setWindowTitle("Revert Tweak Session")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)

        label = QLabel("Select a session to revert. All tweaks in that session will be undone.")
        label.setWordWrap(True)
        layout.addWidget(label)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._populate()

    def _populate(self) -> None:
        self._list.clear()
        sessions = self._backup.list_restore_points()
        for rp in sessions:
            if rp.module != "Tweaks":
                continue
            date = rp.created_at[:19].replace("T", " ")
            item = QListWidgetItem(f"{rp.label} — {date} ({rp.step_count} step(s))")
            item.setData(Qt.ItemDataRole.UserRole, rp.id)
            self._list.addItem(item)

    def selected_restore_point(self) -> Optional[str]:
        cur = self._list.currentItem()
        if cur:
            return cur.data(Qt.ItemDataRole.UserRole)
        return None
```

- [ ] **Step 2: Add Revert button to _build_bottom_bar**

In `_build_bottom_bar`, after the Apply Selected button:

```python
self._revert_btn = QPushButton("Revert Session…")
self._revert_btn.clicked.connect(self._on_revert_session)
layout.insertWidget(1, self._revert_btn)  # after apply button
```

- [ ] **Step 3: Add `_on_revert_session` handler**

```python
def _on_revert_session(self) -> None:
    dialog = RevertDialog(self.app.backup, self._widget)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    rp_id = dialog.selected_restore_point()
    if not rp_id:
        return
    result = self.app.backup.restore_point(rp_id)
    msg = "Revert complete."
    if result.partial:
        msg = f"Partially reverted ({len(result.errors)} error(s))."
    elif not result.success:
        msg = f"Revert failed: {', '.join(result.errors[:3])}"
    QMessageBox.information(self._widget, "Revert", msg)
    self._detect_statuses()
```

- [ ] **Step 4: Test — verify RevertDialog class is defined and no syntax errors**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.tweaks import tweaks_module as tm; print('RevertDialog:', tm.RevertDialog)"`

---

## Task 4: Add per-tweak Details dialog

**Files:**
- Modify: `src/modules/tweaks/tweaks_module.py`

- [ ] **Step 1: Add `TweakDetailsDialog` class before TweaksModule**

```python
class TweakDetailsDialog(QDialog):
    """Shows full details for a tweak: all steps, expected values, impact."""

    def __init__(self, tweak: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tweak.get("name", "Tweak Details"))
        self.setMinimumSize(550, 400)
        layout = QVBoxLayout(self)

        # Header
        header = QLabel(f"<b>{tweak['name']}</b>")
        header.setWordWrap(True)
        layout.addWidget(header)

        desc = QLabel(tweak.get("description", "No description."))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(desc)

        # Risk + restart badge
        badge = QHBoxLayout()
        risk = tweak.get("risk", "low")
        risk_lbl = QLabel(f"Risk: {risk.upper()}")
        risk_lbl.setStyleSheet(
            "color: red; font-weight: bold;" if risk == "high" else
            "color: orange; font-weight: bold;" if risk == "medium" else
            "color: green; font-weight: bold;"
        )
        badge.addWidget(risk_lbl)
        if tweak.get("requires_restart"):
            restart_lbl = QLabel("  🔄 Requires restart")
            restart_lbl.setStyleSheet("color: #ff9800;")
            badge.addWidget(restart_lbl)
        badge.addStretch()
        layout.addLayout(badge)

        # Steps table
        steps_lbl = QLabel("<b>Steps that will be applied:</b>")
        layout.addWidget(steps_lbl)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Type", "Target", "New Value"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for step in tweak.get("steps", []):
            row = table.rowCount()
            table.insertRow(row)
            step_type = step.get("type", "unknown")
            table.setItem(row, 0, QTableWidgetItem(step_type))

            # Target column
            if step_type == "registry":
                target = f"{step.get('key', '')}\\{step.get('value', '')}"
            elif step_type == "service":
                target = step.get("name", "")
            elif step_type == "command":
                target = step.get("cmd", "")[:60] + ("…" if len(step.get("cmd", "")) > 60 else "")
            elif step_type == "appx":
                target = step.get("package", "")
            elif step_type == "scheduled_task":
                target = step.get("task_name", "")
            else:
                target = step.get("key", step.get("name", step.get("cmd", "")))
            table.setItem(row, 1, QTableWidgetItem(target))

            # Value column
            if step_type == "registry":
                val = f"{step.get('data')} ({step.get('kind', 'DWORD')})"
            elif step_type == "service":
                st = step.get("start_type", "manual")
                val = _START_TYPE_MAP_REVERSE.get(str(st).lower(), st)
            elif step_type == "command":
                val = "Run command"
            elif step_type == "appx":
                val = "Remove package"
            elif step_type == "scheduled_task":
                val = "Disable task"
            else:
                val = str(step.get("data", ""))
            table.setItem(row, 2, QTableWidgetItem(val))

        layout.addWidget(table, 1)

        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        close_btn.accepted.connect(self.accept)
        layout.addWidget(close_btn)
```

Add a helper at module level for service start type reverse map:
```python
_START_TYPE_MAP_REVERSE = {v: k for k, v in _START_TYPE_MAP.items()}
```

Wait — `_START_TYPE_MAP` is in `tweak_engine.py`, not accessible here. Define the reverse map locally in `tweaks_module.py`:

```python
_START_TYPE_LABEL = {
    0: "boot", 1: "system", 2: "automatic",
    3: "manual", 4: "disabled"
}
```

- [ ] **Step 2: Add "Details" button to TweakRow**

In `TweakRow.__init__`, after the status_label:

```python
details_btn = QPushButton("ⓘ")
details_btn.setFixedWidth(28)
details_btn.setFlat(True)
details_btn.setToolTip("View tweak details")
details_btn.clicked.connect(lambda: self._show_details())
layout.addWidget(details_btn)
```

Add `self._show_details = lambda: None` in `__init__` (placeholder set by parent). Add method:

```python
def set_details_callback(self, fn) -> None:
    self._show_details = fn
```

- [ ] **Step 3: Wire details callback from TweakTab**

In `TweakTab.__init__`, after creating each row:

```python
for tweak in tweaks:
    row = TweakRow(tweak)
    row.set_details_callback(lambda t=tweak: self._show_tweak_details(t))
    self._rows[tweak["id"]] = row
    self._container_layout.addWidget(row)
```

Add `_show_tweak_details` method to TweakTab:

```python
def _show_tweak_details(self, tweak: Dict) -> None:
    dialog = TweakDetailsDialog(tweak, self.window())
    dialog.exec()
```

- [ ] **Step 4: Test syntax check**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.tweaks import tweaks_module as tm; print('OK')"`

---

## Task 5: Add keyboard shortcuts

**Files:**
- Modify: `src/modules/tweaks/tweaks_module.py`

In `create_widget`, after setting up all tabs and layout, add:

```python
from PyQt6.QtGui import QShortcut, QKeySequence

# Ctrl+F — focus filter on current tab
sc = QShortcut(QKeySequence.StandardKey.Find, self._tabs)
sc.activated.connect(lambda: self._focus_current_filter())

# Ctrl+A — select all in current tab
sc2 = QShortcut(QKeySequence("Ctrl+A"), self._tabs)
sc2.activated.connect(self._select_all_current_tab)

# Ctrl+Shift+A — deselect all in current tab
sc3 = QShortcut(QKeySequence("Ctrl+Shift+A"), self._tabs)
sc3.activated.connect(self._deselect_all_current_tab)
```

Add helper methods to TweaksModule:

```python
def _focus_current_filter(self) -> None:
    tab = self._tabs.currentWidget()
    if hasattr(tab, "_filter_edit"):
        tab._filter_edit.setFocus()
        tab._filter_edit.selectAll()

def _select_all_current_tab(self) -> None:
    tab = self._tabs.currentWidget()
    if isinstance(tab, TweakTab):
        for row in tab._rows.values():
            row.set_checked(True)

def _deselect_all_current_tab(self) -> None:
    tab = self._tabs.currentWidget()
    if isinstance(tab, TweakTab):
        for row in tab._rows.values():
            row.set_checked(False)
```

---

## Task 6: Add applied-count badge to tab labels

**Files:**
- Modify: `src/modules/tweaks/tweaks_module.py`

After `_detect_statuses` completes, update tab labels to show `(N/M applied)`:

```python
def _on_status_detected(self, tweak_id: str, status: str) -> None:
    for tab in self._tab_widgets.values():
        tab.set_status(tweak_id, status)
    # Update tab badges after detection completes
    QTimer.singleShot(500, self._update_tab_badges)
```

Add `_update_tab_badges` method:

```python
from PyQt6.QtCore import QTimer

def _update_tab_badges(self) -> None:
    for i, (category, tab) in enumerate(self._tab_widgets.items()):
        applied = sum(1 for t in tab._tweaks
                      if tab._rows[t["id"]].status_label.text().startswith("✅"))
        total = len(tab._tweaks)
        if applied > 0:
            self._tabs.setTabText(i, f"{category} ({applied}/{total})")
        else:
            self._tabs.setTabText(i, category)
```

Call `_update_tab_badges()` at the end of `_detect_statuses` worker completion. In the `_detect_statuses` worker's result callback:

```python
def _res(data):
    ...
    QTimer.singleShot(0, self._update_tab_badges)
```

And in `_scan_done` / when `self._pending == 0`, call `self._update_tab_badges()` directly.

---

## Task 7: Build and verify

**Files:**
- Test: `src/modules/tweaks/tweaks_module.py`

- [ ] **Step 1: Run full syntax check**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from modules.tweaks import tweaks_module; print('All imports OK')"`

- [ ] **Step 2: Run app and check Tweaks tab**

Run: `python src/main.py` (or launch the built exe)
Navigate to: **Tweaks** tab → verify:
- [ ] Search bar appears at top of each category tab
- [ ] Typing in search filters rows in real-time
- [ ] "Details" (ⓘ) button appears on each row
- [ ] Clicking "Details" opens dialog with step table
- [ ] Revert Session button appears in bottom bar
- [ ] Clicking "Revert Session" opens session list dialog
- [ ] Tab labels show `(N/M applied)` after detection completes
- [ ] Status labels show 🔄 for service-tweak rows
- [ ] Ctrl+F focuses the filter input
- [ ] Ctrl+A selects all in current tab

---

## Task 8: Commit

```bash
git add src/modules/tweaks/tweaks_module.py src/modules/tweaks/tweak_engine.py
git commit -m "feat(tweaks): add search/filter, revert session, details dialog, restart indicators

- TweakTab: add QLineEdit filter bar with real-time name/description search
- TweakRow: add Details (ⓘ) button that opens TweakDetailsDialog with step table
- TweakDetailsDialog: shows all steps with type, target, and new value
- RevertDialog: lists Tweaks restore points for undo of entire sessions
- TweakEngine.requires_restart(): detects service changes and known-restart registry keys
- Status labels show 🔄 for restart-required tweaks
- Tab labels update to (applied/total) after detection completes
- Keyboard shortcuts: Ctrl+F (search), Ctrl+A (select all), Ctrl+Shift+A (deselect)
"
```