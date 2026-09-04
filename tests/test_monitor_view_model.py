r"""What the tab says about your monitors, decided outside the widget.

The headline banner is the part of this feature that earns its place: it
turns a settings panel into something that tells you a thing you did not
know. On the machine this was written for it has something to say — both
displays run at 60 Hz on panels that offer 144 and 120.

That makes it worth testing properly, which means keeping it out of the
widget. Everything here is a pure function over view models.

The rules it has to get right are all "do not overstate":

* A monitor is only "running below its best" when a FASTER rate exists **at
  the resolution it is actually using**. Offering 144 Hz at 1080p says
  nothing about a display running 1440p.
* Silence when there is nothing to report. A banner that always says
  something is a banner nobody reads.
* Never recommend a downsampled resolution as an improvement.
"""
import pytest

from modules.monitor_control import view_model as vm


def _view(name="Panel", active=True, resolution=(2560, 1440), refresh=60.0,
          rates=(60.0, 120.0, 144.0), native=(2560, 1440), target_id=1,
          connector="HDMI"):
    return vm.MonitorView(
        target_id=target_id, name=name, connector=connector, adapter="GPU",
        active=active, resolution=resolution, position=(0, 0),
        refresh_hz=refresh, rates_at_resolution=tuple(rates),
        native_resolution=native, device_name=r"\\.\DISPLAY1",
        audio_endpoint=None, audio_is_default=False, ddc=None)


# ── running below the panel's best ─────────────────────────────────────

def test_a_display_at_60_on_a_144_panel_is_below_its_best():
    view = _view(refresh=60.0, rates=(60.0, 120.0, 144.0))
    assert vm.best_available_rate(view) == 144.0
    assert vm.is_below_best(view) is True


def test_a_display_already_at_its_fastest_is_not_flagged():
    view = _view(refresh=144.0, rates=(60.0, 120.0, 144.0))
    assert vm.is_below_best(view) is False


def test_rates_at_another_resolution_do_not_count():
    """144 Hz at 1080p says nothing about a display running 1440p."""
    view = _view(refresh=60.0, resolution=(2560, 1440), rates=(60.0,))
    assert vm.is_below_best(view) is False


def test_an_inactive_display_is_never_flagged():
    view = _view(active=False, resolution=None, refresh=0.0, rates=())
    assert vm.is_below_best(view) is False


def test_a_display_with_no_known_rates_is_not_flagged():
    """Not knowing is not the same as knowing it is fine."""
    view = _view(refresh=60.0, rates=())
    assert vm.is_below_best(view) is False
    assert vm.best_available_rate(view) is None


# ── the headline ───────────────────────────────────────────────────────

def test_the_headline_counts_active_against_connected():
    views = [_view(name="A", target_id=1), _view(name="B", target_id=2),
             _view(name="C", target_id=3, active=False, resolution=None,
                   refresh=0.0, rates=())]
    assert "2 of 3" in vm.headline(views)


def test_the_headline_names_the_worst_offender_and_its_ceiling():
    views = [
        _view(name="Fast", target_id=1, refresh=144.0,
              rates=(60.0, 144.0)),
        _view(name="Slow", target_id=2, refresh=60.0,
              rates=(60.0, 120.0, 240.0)),
    ]
    text = vm.headline(views)
    assert "Slow" in text
    assert "240" in text
    assert "Fast" not in text, "named a display that is already at its best"


def test_the_headline_is_empty_when_everything_is_at_its_best():
    views = [_view(name="A", refresh=144.0, rates=(60.0, 144.0)),
             _view(name="B", target_id=2, refresh=120.0, rates=(120.0,))]
    assert vm.headline(views) == ""


def test_the_headline_mentions_a_disconnected_monitor():
    views = [_view(name="A", refresh=144.0, rates=(144.0,)),
             _view(name="Idle", target_id=2, active=False, resolution=None,
                   refresh=0.0, rates=())]
    assert "Idle" in vm.headline(views)


def test_no_monitors_at_all_says_nothing():
    assert vm.headline([]) == ""


# ── the one-click fix ──────────────────────────────────────────────────

def test_the_fix_targets_every_display_below_its_best():
    views = [
        _view(name="A", target_id=1, refresh=60.0, rates=(60.0, 144.0)),
        _view(name="B", target_id=2, refresh=120.0, rates=(120.0,)),
        _view(name="C", target_id=3, refresh=60.0, rates=(60.0, 240.0)),
    ]
    fixes = vm.raise_refresh_plan(views)
    assert [(f.target_id, f.to_rate) for f in fixes] == [(1, 144.0), (3, 240.0)]


def test_the_fix_keeps_the_resolution_it_is_already_using():
    """Raising the rate must not also change resolution underneath someone."""
    view = _view(refresh=60.0, resolution=(2560, 1440),
                 rates=(60.0, 240.0), native=(2560, 1440))
    fix = vm.raise_refresh_plan([view])[0]
    assert fix.resolution == (2560, 1440)


def test_nothing_to_fix_is_an_empty_plan():
    assert vm.raise_refresh_plan([_view(refresh=144.0, rates=(144.0,))]) == []


# ── how a monitor is described in its card ─────────────────────────────

def test_an_active_monitor_reads_as_its_mode():
    view = _view(name="S2719DGF", refresh=60.0)
    assert vm.describe(view) == "2560x1440 @ 60 Hz"


def test_a_fractional_rate_keeps_its_decimal():
    """59.94 Hz is a real mode and rounding it to 60 names a different one."""
    view = _view(refresh=59.94, rates=(59.94,))
    assert "59.94" in vm.describe(view)


def test_an_inactive_monitor_says_so_rather_than_showing_zeroes():
    view = _view(active=False, resolution=None, refresh=0.0, rates=())
    assert vm.describe(view) == "connected, not in use"


def test_a_downsampled_resolution_is_called_out():
    """Running above native means the GPU is scaling — worth knowing."""
    view = _view(resolution=(3840, 2160), native=(2560, 1440), refresh=120.0)
    assert vm.is_downsampled(view) is True
    assert "scaled" in vm.describe(view).lower()


def test_running_at_native_is_not_called_downsampled():
    assert vm.is_downsampled(_view(resolution=(2560, 1440),
                                   native=(2560, 1440))) is False


def test_an_unknown_native_resolution_makes_no_claim():
    assert vm.is_downsampled(_view(native=None)) is False
