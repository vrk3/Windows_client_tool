# Monitor Control — plan and handoff

**Branch:** `feat/monitor-control` (11 commits ahead of `master`, unmerged)
**Written:** 2026-09-04, mid-flight, immediately before an OS reinstall.

This document exists because the first two stages were executed from a plan
that only ever lived in a session's context. Everything below was
reconstructed from the code and the commit messages on the branch, so it is
accurate about what is *there*; the "remaining" section is the design as the
code already implies it, not a wish list.

## What the module is

One tab that shows what the displays are doing and changes them. The engine
half is pure Python with no Qt and no display required, so all of it is
tested against captured fixtures from this machine (3 monitors: a Gigabyte
MO27Q28G, a Dell, and an LG ULTRAWIDE that is connected and switched off).

`src/modules/monitor_control/`

| File | Role | In the UI? |
|---|---|---|
| `display_config.py` | CCD topology reader (`QueryDisplayConfig`) — the only source of truth | yes |
| `display_modes.py` | what each display *could* do (mode enumeration) | via `view_model` |
| `monitor_identity.py` | friendly names, device paths, EDID native resolution | via `view_model` |
| `display_writes.py` | the write layer: modes, Win+P arrangements, connect/disconnect | yes |
| `_apply_guard.py` | snapshot -> apply -> 15s countdown -> revert unless confirmed | yes |
| `view_model.py` | joins the engines into one `MonitorView` per monitor + the headline | yes |
| `_arrangement_canvas.py`, `_arrangement_geometry.py`, `_screen_overlay.py` | the map, and Identify | yes |
| `ddc.py` | DDC/CI over Dxva2 — brightness, contrast, input source | **NO** |
| `display_audio.py` | which monitor carries which audio endpoint | **NO** |
| `profiles.py` | named display profiles keyed on EDID | **NO** |
| `window_layout.py`, `window_census.py` | capture and restore window positions | **NO** |

The four unwired files are complete and tested (`tests/test_ddc.py`,
`tests/test_display_audio.py`, `tests/test_monitor_profiles.py`,
`tests/test_window_layout.py`). They are engines with no caller yet.

## The one rule the module is built around

**Every display change goes through `_apply_guard`.** Snapshot, apply, then a
15-second countdown that puts it back unless someone confirms. Nothing in
`monitor_module.py` calls a write function directly.

The failure being designed around is a mode the monitor cannot show: the
screen goes dark and the control that would undo it is on that screen. Doing
nothing has to be the safe answer, so doing nothing reverts. Three
corollaries already implemented and worth not breaking:

* The confirm window is placed on a screen that still exists *after* the
  change (`choose_confirm_screen`).
* A failed apply starts no countdown, and a change whose snapshot could not
  be taken is refused rather than attempted hopefully.
* The revert replays the **raw** path and mode arrays captured before the
  change, not a reconstruction from a parsed copy.

## Done

**Stage 1.1 — read.** Commits `8a7fdb8` … `e11ad73`. Topology, identity,
modes, DDC, audio, profiles, window layout, the safety guard, the canvas,
the view model, the tab itself, and `tools/monitor_control_check.py` as a
read-only harness against the real hardware.

**Stage 1.2 — write.** Commits `6fca531`, `e28b8dd`, `db87414`. The write
layer, the revert countdown proven against a real display, and every button
wired through the guard:

* "Use highest refresh rate" — appears only when something is actually below
  its best, and raises each display *at the resolution it already has*.
  Batched through `apply_modes`, which refuses the whole set if any one mode
  is unavailable.
* The four Win+P arrangements, via `SDC_TOPOLOGY_*` rather than
  `DisplaySwitch.exe`: the flag form returns a result that can be reported,
  where the exe returns before Windows has finished and tells you nothing.
  Never OR-ed with `SDC_USE_SUPPLIED_DISPLAY_CONFIG` — they are two different
  ways of saying what to apply and combining them is
  `ERROR_INVALID_PARAMETER`.
* Connect / Disconnect per monitor, refusing to switch off the last one.

Suite at the tip of the branch: `PYTEST_EXIT=0`, no failures.

## Remaining

### Stage 1.3 — DDC controls and the audio a monitor carries

`MonitorView` already has the three fields for this and nothing populates
them: `audio_endpoint`, `audio_is_default`, `ddc`. That is the seam.

1. `view_model.build_views()` fills them, each call guarded the way the
   existing engine calls are — one unreadable field must not cost the list.
   Note `ddc.open_monitors()` is a context manager because physical monitor
   handles leak; do not hold a handle across a refresh.
2. The monitor card grows:
   * **Audio, read-only.** Which endpoint this monitor carries and whether it
     is the current default output. `endpoint_for_monitor` returns None when
     two live endpoints answer to the same name — show "could not tell them
     apart", never a coin flip.
   * **Brightness / contrast**, only when `DdcCapability.responded` and the
     corresponding `supports_*` is true. Never assume a 0..100 range; the
     monitor's own `maximum` is authoritative, and a maximum of 0 means the
     reply was junk, not a control with no range.
   * **Input source**, only when `input_sources_known` — the capabilities
     string is the only honest list, and `set_input_source` already refuses
     to guess.
3. **Which of these needs the countdown.** Brightness and contrast do not:
   the control that undoes them is the same slider, on the same screen, still
   reachable. Input source does — switching the panel to another input takes
   the app off the screen, and "doing nothing reverts" is exactly right
   there. Its snapshot/restore is the old VCP value, not the topology arrays,
   so `_guarded()` needs a snapshot/restore pair passed in rather than the
   hardcoded `dc.raw_topology_arrays()` it uses today.
4. Report `WriteResult.verified` honestly. `False` means the monitor took the
   call and ignored it — common, and the user should be told rather than
   shown a slider that silently snaps back.

**Not to be wired without a supervised first run:** the *audio endpoint
enable/disable* writes in `display_audio.py`. They drive
`IPolicyConfig::SetEndpointVisibility`, an undocumented interface with no
published header, and **nothing in that file has ever been executed against a
real endpoint**. It is behind a `confirm_supervised=True` interlock for that
reason. Before it is trusted it needs: disable -> re-read the state ->
re-enable -> re-read, on an endpoint nobody is listening to, confirming the
state actually moved and actually came back. Disabling the wrong one takes
the sound off the machine.

### Stage 2 — display profiles

`profiles.py` is complete and unwired. Save "this is what my desk looks
like", apply it later. Identity is the **EDID** (manufacturer, product code,
serial), because `\\.\DISPLAY1` is a position in a list, and the CCD target
id and the device-path UID are both the adapter output, not the panel.
`can_apply` refuses by name when a monitor's EDID could not be read.

UI: a profile list, Save current, Apply, Delete. Apply goes through the guard
like everything else — it is the largest change the module can make.

### Stage 3 — window layout

`window_layout.py` + `window_census.py`, also complete and unwired. Capture
where every window is and put them back after the monitors change. The
natural trigger is the `screenAdded` / `screenRemoved` signals the module
already listens to.

## Where to pick it up

```
git checkout feat/monitor-control
python tools/monitor_control_check.py     # read-only, prints what the hardware says
python -m pytest tests/ -q                # whole suite; last run PYTEST_EXIT=0
python src/main.py                        # the tab is under System
```

`tools/monitor_revert_check.py` exercises the countdown against a real
display. Both harnesses are read-only until told otherwise.

Note that the module declares `requires_admin` with `read_only_unelevated`:
display and DDC work needs no elevation at all, and only the audio endpoint
writes do. Gating the whole module on admin would disable a tab that is
mostly usable without it — the same reasoning as `debloat_module.py` and
`store_apps_module.py`.
