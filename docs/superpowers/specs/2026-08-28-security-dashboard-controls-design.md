# Security Dashboard — Actionable Controls, Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** Security Dashboard, phase 2 — from read-only to actionable
**Date:** 2026-08-28
**Status:** Awaiting review
**Module:** `src/modules/security_dashboard/`
**Extends:** the Security Dashboard as it stands at `d57cdf2`

---

## 1. Overview

The Security Dashboard can see 171 things about this machine and change 24 of
them. The other 147 are not blocked by Windows — they are blocked by the fact
that every card in the pane is hand-written and hand-wired to one setter, so
adding a control means writing a widget, an attribute, a setter and a wiring
line by hand. Nobody was ever going to do that 147 times.

This spec replaces the hand-wired pane with a **declarative catalog of security
controls**. One entry per control carries its reader, its writer, its risk class
and its metadata; the tabs, the search, the baselines, the exported profiles and
the Overview verdict all become filters and aggregates over that one table.

It also moves every write onto the app's existing `TweakEngine` /
`BackupService` machinery, which already records the prior value of each step
and can restore it. The dashboard currently writes with neither.

### 1.1 Measured starting state

Counted at `d57cdf2`, not estimated:

| | |
|---|---|
| `security_reader.py` | 3,277 lines, 231 top-level defs |
| `check_*` functions | **171** |
| `set_*` functions | **44** |
| `security_module.py` | 1,478 lines, 5 tabs |
| `_ToggleCard` instances (things you can actually change) | **24** |
| Hardcoded hex colours in the UI module | 40 |
| Top-level functions defined **more than once** | **10** |

### 1.2 Recorded decisions

Decided during brainstorming, recorded so they are not re-litigated:

1. **Coverage is everything Windows permits, risk-classified** — not a curated
   safe subset. A control Windows will not let us write stays read-only *and
   says why*.
2. **Changes stage, then apply as one elevated batch** — one UAC prompt per
   batch, not per click, and not a whole-app relaunch.
3. **Themed tabs plus a search/filter bar** spanning all of them, replacing the
   "Controls"/"Advanced" grab-bags.
4. **In scope:** one-click baselines, change history with per-change and
   per-batch revert, profile export/import.
5. **Out of scope:** drift detection. Explicitly excluded by the user.
6. Approach **A** (declarative catalog + `TweakEngine` as the write path) was
   chosen over extending the hand-wired pattern, and over folding security into
   the Tweaks module's `security.json`. A tweak is apply-only; a security
   control is a two-way toggle with a live reading, and conflating them would
   lose the verdict cards, the CVE grid and the event log.

### 1.3 Three defects this work is built on top of

These were found while reading the existing code, and the design accounts for
each. They are stated here because two of them make the current pane report
success it has not earned.

**A. `security_reader.py` defines ten functions twice.** An AST scan of the
module's 231 top-level defs finds ten names bound twice, where the second
binding silently shadows the first — and the two implementations do not agree,
because they are built on two different helpers with opposite polarity
(`_check_service(good_running=...)` at ~line 2172 versus `_svc_check(running_bad=...)`
at ~line 2599):

| Function | Defined at | Live definition |
|---|---|---|
| `check_service_dnscache` | 2192, 2632 | 2632 |
| `check_service_dhcp` | 2195, 2633 | 2633 |
| `check_service_wsearch` | 2204, 2634 | 2634 |
| `check_service_sysmain` | 2207, 2635 | 2635 |
| `check_service_fax` | 2210, 2636 | 2636 |
| `check_service_xbox_live` | 2213, 2637 | 2637 |
| `check_service_wpn` | 2225, 2639 | 2639 |
| `check_service_fdphost` | 2234, 2641 | 2641 |
| `check_service_webclient` | 2249, 2642 | 2642 |
| `check_fast_startup` | 2441, 2742 | 2742 |

This is the same shape as the `shell.py` duplicate-method bug from phase 1: both
definitions are syntactically fine and the suite stays green. There is already an
AST test for this over `ui/` modules only. It gets extended to every module (§7.2).

**Corrected 2026-08-28, after implementation.** This section originally said the
answer was "decided by file order", implying the pane might show either verdict.
That was wrong, and resolving the duplicates established what is actually true:
all ten *losing* definitions were **dead code**. No dict, registry, alias or
string lookup referenced any of the ten names anywhere in `src/`, so the second
definition always won at import and the pane was consistently showing it. The
damage was narrower than claimed and concentrated in one place — `check_fast_startup`,
whose live definition mapped an **absent** `HiberbootEnabled` value to
"Disabled"/green. That is this project's recurring defect, not a duplication
defect: *a refused or missing read reported as a good verdict.* The surviving
definition returns "Not Configured".

Widening the AST test found an eleventh instance the ten never hinted at:
`ServicesModule._do_refresh` in `src/modules/services_manager/services_module.py`,
defined twice with byte-identical bodies. The `ui/`-only scope of the old test is
why nobody had seen it. That is the argument for §7.2 restated as evidence: the
test's value was not in fixing the ten it was written for.

**B. The write path cannot tell you a change failed.** `TweakEngine._apply_command`
and `_apply_script` both run `subprocess.run(cmd, shell=True, check=False,
capture_output=True)` and then look at neither the return code nor the captured
output. The `StepRecord` is built and recorded regardless. Every command-shaped
write in the app is therefore reported as applied whether Windows did it or not.

This matters more here than in the Tweaks module. This project's ledger already
records, repeatedly, that Windows admin commands **exit 0 while refusing**
(`Get-Tpm` answering `TpmPresent: null`, `Get-BitLockerVolume` writing "Access
denied" to stderr with empty stdout, `dism /get-features` exiting 740 with its
complaint on stdout, `gpresult /x` writing a valid report with the computer half
silently dropped). A pane that says "Firewall: on" when the write was refused is
worse than one that never offered the button.

**C. `_ToggleCard`'s revert is a guess.** `configure()` defaults `revert_fn` to
`toggle_fn`, so "Revert" calls the setter with the opposite argument. That
assumes the setting was binary and that its previous value was the opposite of
what you just set — neither is reliably true, and for a multi-valued setting
(`NtlmMinClientSec`, cached logon count, cloud block level) it is simply wrong.
`BackupService.revert_step` already does this correctly, restoring the recorded
`before_value` and deleting a value that did not previously exist. The guess is
removed.

---

## 2. Architecture

```
security_dashboard/
  catalog/
    __init__.py          registry: load_catalog() -> Dict[str, SecurityControl]
    model.py             SecurityControl, Risk, Category, ControlState
    defender.py          ~45 controls
    firewall_network.py  ~30
    accounts.py          ~20
    device_boot.py       ~15
    services.py          ~20
    features.py          ~10
    exploit_cve.py       ~15
    baselines/
      recommended.json   {id: desired} — the catalog's own `desired` field
      hardened.json
      developer.json
  staging.py             PendingChange, ChangeSet, diffing, baseline -> ChangeSet
  applier.py             batch execution, verify-after-write, result model
  elevated_helper.py     the --apply-security-batch entry point
  profile.py             export/import + diff against live readings
  security_reader.py     unchanged readers (the 171), duplicates resolved
  security_module.py     the pane — renders from the catalog, wires nothing
```

Only `security_module.py` imports Qt. `catalog/`, `staging.py`, `applier.py`,
`profile.py` and `elevated_helper.py` are pure logic and are testable without a
`QApplication`. This follows the split the Group Policy subsystem landed on,
where ten modules exist and three import Qt.

### 2.1 `SecurityControl`

```python
@dataclass(frozen=True)
class SecurityControl:
    id: str                          # stable, used by baselines and profiles
    title: str
    category: Category
    description: str                 # what it is
    why_it_matters: str              # what an attacker does without it
    reader: Callable[[], Dict[str, Any]]   # one of the existing check_* fns
    on_steps: Tuple[Dict, ...] = ()  # TweakEngine step dicts, verbatim schema
    off_steps: Tuple[Dict, ...] = ()
    desired: Optional[bool] = None   # what "recommended" means; None = no opinion
    risk: Risk = Risk.LOW
    requires_admin: bool = True
    requires_reboot: bool = False
    read_only_reason: Optional[str] = None
    docs_url: Optional[str] = None
```

`reader` is one of the 171 existing `check_*` functions, reused unchanged. The
catalog is a binding layer, not a rewrite of the readers.

**Why the file counts above total ~155 and not 171.** The 171 are not 171
distinct controls. Ten are the duplicate bindings of §1.3 A and collapse to
five once resolved; a handful are aggregates rather than controls
(`get_overview_status`, `get_extended_status`, `check_defender_signatures`,
`check_listening_ports`, `check_tpm_details`) and stay as Overview inputs or
read-only detail cards rather than becoming toggles. The catalog is therefore
*more* than a 1:1 wrapping in some places and less in others, and the binding
test in §7.1 asserts the mapping rather than the count: **every `check_*`
function in `security_reader.py` is either bound to a catalog entry or named in
an explicit `NOT_A_CONTROL` list with a reason.** An unbound reader is a test
failure, so a check cannot quietly fail to reach the pane the way 147 of them
do today.

`on_steps` / `off_steps` use the `TweakEngine` step schema verbatim — `registry`,
`service`, `command`, `script`, `appx`, `scheduled_task` — so the engine needs no
new step types.

**A control with no steps must set `read_only_reason`.** It renders as a status
card that states why it cannot be changed ("TPM presence is a hardware fact",
"Secure Boot is set in firmware, not by Windows", "changing this requires
Windows Setup media"). This is the design's answer to the 147: a control we
cannot write is *visibly* read-only with a reason, never silently absent. A test
enforces the invariant (§7.1).

### 2.2 Writer selection rule

Where a setting has both a registry representation and a cmdlet, **the registry
step wins**. `BackupService.revert_step` restores registry and service steps
exactly, from the recorded prior value; `command` steps it cannot revert at all
(it logs a warning and marks them reverted), and `script` steps it can only
revert via an explicit `revert_command`.

Where a cmdlet is genuinely the only way — most of `Set-MpPreference`, some of
`Set-NetFirewallProfile` — the control uses a `script` step and its
`revert_command` is **computed at stage time** from the reader's current value,
not hardcoded in the catalog. A `Set-MpPreference -DisableRealtimeMonitoring
$true` staged while the reader says realtime monitoring is currently on gets
`Set-MpPreference -DisableRealtimeMonitoring $false` as its revert.

This is the one place the design writes a value into a step at staging time
rather than reading it from a static definition, and it exists because a static
revert command cannot know what it is reverting to.

---

## 3. The write path

### 3.1 Staging

Toggling a card creates a `PendingChange(control_id, from_value, to_value)` and
changes nothing on the machine. A bar across the bottom of the pane shows
`N changes pending — Review · Apply · Discard`.

**Review** opens a table: control, from → to, risk, whether a reboot is needed,
and the literal steps that will run. Nothing about what is going to happen is
hidden behind a friendly label.

Staging works unelevated. You can open the pane without admin rights, read
everything, decide what you want, and only then be asked to elevate.

### 3.2 Apply

In order:

1. **`BackupService.create_restore_point(label, module="Security Dashboard")`** —
   always. This is the app's own SQLite-backed record and is what per-batch
   revert unwinds. It is cheap.
2. **`core.system_restore.create_restore_point()`** — only when the batch
   contains at least one `Risk.HIGH` control. A Windows restore point costs
   30+ seconds and is not warranted for toggling LLMNR.
3. **Elevation.** If already elevated, execute in-process. If not, serialise the
   batch to JSON under the app data directory and launch

   ```
   <sys.executable> --apply-security-batch <batch.json> --result <result.json>
   ```

   via `ShellExecuteW(None, "runas", ...)`, then wait on the result file.

   The command line is built with `subprocess.list2cmdline()`, **not** with
   `" ".join(sys.argv)`. `core.admin_utils.restart_as_admin` uses the naive join
   today and would break on any path containing a space; the app data path
   contains `C:\Users\iorda\AppData\...`, so this is not hypothetical. Fixing
   `restart_as_admin` itself is noted in §8 as adjacent, not assumed here.

   The helper writes its own result file rather than having its output
   redirected. `ShellExecuteW`-launched processes cannot have their stdout
   captured by the parent — this project has already paid for that lesson once
   with elevated PowerShell.

4. **Per control:** `TweakEngine.apply_tweak({"id": control.id, "steps": steps},
   rp_id)`, so each step is backed up and recorded exactly as a tweak is.
5. **Verify after write** (§3.3).

### 3.3 Verify after write

After a control's steps are applied, its `reader` is called again and the result
compared against what was asked for. This is the core of the design and it is
what defect **B** makes necessary.

Every control in a batch lands in exactly one of four states:

| State | Meaning |
|---|---|
| `APPLIED_VERIFIED` | the reader now agrees with the requested value |
| `APPLIED_PENDING_REBOOT` | writer succeeded, control declares `requires_reboot`; verification is deferred and the card says so |
| `APPLIED_UNVERIFIED` | writer reported success, reader still disagrees |
| `REFUSED` | with the reason |

`APPLIED_UNVERIFIED` is the state that today does not exist and is reported as
success. It is rendered distinctly — amber, with the reader's actual value shown
next to the requested one — because it is the state that means *something else
on this machine is overriding you*: a Group Policy, Tamper Protection, an
MDM enrolment, or another security product.

A `REFUSED` reason is assembled from **stdout and stderr together**, never from
the return code alone. The ledger's rule is explicit and has cost this project
four defects in one session: *never treat `rc` as a success signal for a Windows
admin cmdlet.* `netsh` and `dism` both write their real complaint to stdout.

To make this possible, `_apply_command` and `_apply_script` gain rc/stdout/stderr
capture on the `StepRecord`. Existing callers discard those fields today, so
nothing changes for the Tweaks module except that it becomes able to tell the
truth later.

### 3.4 Result report

Apply ends with a report, not a toast: a list of every control in the batch with
its final state, the reader's before and after values, and the reason for
anything refused. A batch where 9 of 12 worked must not look like a batch where
12 worked.

---

## 4. Revert, history, baselines, profiles

### 4.1 Revert

Delegated entirely to `BackupService`, which already does it correctly:

- `revert_step(step_id)` — one change. Restores the recorded `before_value` for
  registry and service steps, and **deletes a registry value that did not exist
  before**, which is the case a guess-the-opposite revert gets wrong every time.
- `revert_tweak(control_id)` — every step of one control.
- `restore_point(rp_id)` — a whole batch, in reverse.

`_ToggleCard`'s `revert_fn` defaulting to `toggle_fn` is removed (defect **C**).

Revert is followed by the same verify pass as apply. A revert that did not take
is reported, not assumed.

### 4.2 History tab

Reads `BackupService.list_restore_points()` and the steps under each: what
changed, when, old → new, and which module did it. Rows offer *Revert this
change* and *Revert this batch*. Steps already reverted show their
`reverted_at`; steps whose revert failed show the recorded `revert_error`
rather than nothing.

### 4.3 Baselines

`{control_id: desired}` maps under `catalog/baselines/`, surfaced through the
existing `PresetManager`, which already ships `corporate_hardened.json` and the
save / load / delete / export / import operations.

- **Recommended** — the catalog's own `desired` field across every control that
  has an opinion.
- **Hardened** — Recommended plus the medium-risk hardening most machines can
  take.
- **Developer machine** — Recommended minus the controls that break WSL,
  Hyper-V, local IIS and unsigned-script development.

Applying a baseline **stages a diff, it does not apply blindly**: it shows what
it will change, and — equally important — what it will skip and why (already
compliant, no writer, hardware-refused, would need a reboot).

### 4.4 Profile export / import

Export writes the current reading of every control to JSON with the app version
and the OS build. Import shows a diff against this machine's live readings
before anything is staged, so applying another machine's profile is a reviewed
operation rather than a leap.

---

## 5. The pane

### 5.1 Tabs

`Overview · Defender · Firewall & Network · Accounts & Credentials · Device &
Boot · Services · Windows Features · Exploit & CVE · History · Events`

"Controls" and "Advanced" are retired. They were hand-grouped grab-bags at 24
controls and would be unnavigable at 150.

### 5.2 The filter bar

Persistent, above the tabs, spanning all of them:

- free-text filter over title, description and `why_it_matters`
- **Only problems** — controls whose reading disagrees with `desired`
- **Only changed from default**
- **Only actionable now** — has a writer, and admin state permits it

"Only problems" turns the whole pane into a work queue, which is the thing that
makes 150 controls usable rather than exhausting.

### 5.3 Overview

Keeps its verdict cards and keeps the 2026-08-24 fix: it computes only the
checks it draws (14 cards, not a 78-check sweep), and it does not run an
auto-refresh timer that relaunches an unfinished sweep. Any aggregate over the
catalog for Overview must respect that — a "score across 150 controls" that
re-runs 150 readers on a timer would reintroduce exactly the defect that was
removed.

### 5.4 CVE tab

The eleven CVE cards (Spectre v2, Meltdown, SSBD, L1TF, MDS, PrintNightmare,
Zerologon, PetitPotam, Follina, BlackLotus, Kerberos armoring) become catalog
entries like any other. Most have registry-settable mitigations and get real
controls; the ones that are microcode- or patch-dependent get
`read_only_reason` naming what actually fixes them.

### 5.5 Theme

The 40 hardcoded hex colours move to theme tokens. The `#999` description text
under each card measures roughly 2.8:1 on the light theme's white and is
replaced with a token that meets 4.5:1 in both themes. The pane already passes
`test_theme_light_coverage.py`, which measures dominant background luminance —
that test cannot see a low-contrast label, so the fix is verified by rendering
the pane in both themes and looking at it.

---

## 6. Error handling

| Situation | Behaviour |
|---|---|
| Not elevated, batch needs admin | Stage freely; Apply raises one UAC prompt for the whole batch |
| UAC declined | Batch stays staged, nothing applied, nothing lost |
| Elevated helper crashes / writes no result | Batch reported as unknown-outcome; readers re-run and the pane shows actual current state rather than assuming failure |
| A single control refuses | Batch continues; that control reports `REFUSED` with its reason |
| Writer succeeds, reader disagrees | `APPLIED_UNVERIFIED`, amber, both values shown |
| Reader itself fails | The control shows "could not read" with the reason — never an assumed value. A refused read is not an unset value |
| Reboot required | `APPLIED_PENDING_REBOOT`; the pane offers a single consolidated reboot prompt at the end of a batch, not one per control |

The last row of that table is the Group Policy subsystem's own rule, restated:
*a refused read is never reported as an absent value.* It applies identically
here.

---

## 7. Testing

### 7.1 Catalog invariants

Cheap, and they are what keeps 150 entries honest:

- every `id` unique
- every entry has a `reader` that is callable
- every entry with no `on_steps`/`off_steps` has a non-empty `read_only_reason`
- every entry with steps has `requires_admin` set deliberately
- **every `check_*` function in `security_reader.py` is either bound to a
  catalog entry or listed in `NOT_A_CONTROL` with a reason** — this is the
  invariant that stops a reader silently failing to reach the pane
- every step dict parses under the `TweakEngine` schema
- every baseline references only ids that exist in the catalog
- `desired` is set for every control that appears in the Recommended baseline

### 7.2 Duplicate-definition test

The existing AST duplicate test over `ui/` is extended to every module under
`src/`, which is what catches defect **A** and stops it recurring in a catalog
split across seven files.

### 7.3 Logic tests

Staging, diffing, baseline → `ChangeSet`, profile import diff, and the four-state
classification, all against a fake engine and fake readers. No `QApplication`
required.

### 7.4 What actually counts as evidence

Per this project's record — **a green suite has proved nothing eight times** —
the tests above are necessary and are not the evidence. Before any claim that
this works:

1. A harness (`tools/security_catalog_check.py`) that drives the **real** catalog
   against this machine: read every control, report anything that fails to read
   or reads as unknown, and count how many of the 150 the machine can actually
   answer. Run unelevated and elevated, and diff — the same technique
   `tools/admin_requirement_audit.py` uses for module read paths.
2. A round-trip on a low-risk control on this machine: apply → verify → revert →
   verify, with the registry value read directly at each step, not through the
   reader that was just used to decide.
3. Render the pane in both themes and look at it, including with a batch staged,
   mid-apply, and showing a report with a refused control in it.
4. Column widths measured against the real dump, not guessed —
   `fontMetrics().horizontalAdvance()` per column against a full catalog load.
   The Firewall table clipped 393 of 544 real rows on defaults.

---

## 8. Out of scope

- **Drift detection.** Excluded by the user.
- **Remote or domain-wide application.** This pane configures this machine.
- Fixing `core.admin_utils.restart_as_admin`'s unquoted `" ".join(sys.argv)`.
  It is a real latent bug and it is adjacent, not part of this work; the new
  elevated helper does not use it. Recorded here so it is not lost.
- Controls Windows will not let us set. They stay read-only with a stated
  reason, which is a feature of this design rather than a gap in it.
