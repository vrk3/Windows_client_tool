r"""What a servicing code usually means, and what to do about it.

`describe()` already names a code. Naming is not explaining: someone who
reads "CBS_E_INVALID_PACKAGE" still has to go and look it up.

The hard rule here is that **nothing is invented**. A cause and a remedy are
offered only for codes whose behaviour is documented and whose remedy is
checkable; every other code keeps the name-only behaviour it has today. A
plausible-sounding fix for the wrong error costs more time than no fix at
all, because it is acted on.
"""

from modules.log_viewer.error_codes import advice, describe


def test_a_documented_servicing_code_carries_a_cause_and_a_remedy():
    note = advice(0x800F081F)
    assert note is not None
    assert note.cause and note.remedy


def test_the_remedy_names_a_real_command():
    """A remedy has to be something someone can actually run."""
    note = advice(0x800F081F)
    assert "DISM" in note.remedy or "sfc" in note.remedy.lower()


def test_an_unknown_code_gets_no_advice_at_all():
    """Silence beats a guess -- the rule `describe` already follows."""
    assert advice(0x12345678) is None


def test_a_success_code_gets_no_advice():
    assert advice(0x00000000) is None


def test_every_entry_has_both_halves_and_a_source():
    """A cause with no remedy is half an answer; a remedy with no reason is
    cargo cult. The reference is what makes each one checkable."""
    from modules.log_viewer.error_codes import CODE_ADVICE

    assert CODE_ADVICE
    for code, note in CODE_ADVICE.items():
        assert note.cause.strip(), f"{code:#010x} has no cause"
        assert note.remedy.strip(), f"{code:#010x} has no remedy"
        assert note.reference.strip(), f"{code:#010x} cites no source"


def test_advice_does_not_replace_the_name():
    """The name still comes from describe(); advice is additional.

    0x80070490 rather than a CBS_E_* code because only the Win32 facility
    (0x8007xxxx) has a name Windows itself will supply -- `describe` returns
    "" for the CBS codes, which is exactly its documented behaviour.
    """
    assert describe(0x80070490)
    assert advice(0x80070490).cause != describe(0x80070490)


def test_the_codes_this_machine_actually_shows_are_covered():
    r"""0x80004005 appears 522 times in this machine's CBS archive and
    0x80070490 five times. A knowledge base that skips the codes actually
    present is decoration."""
    for code in (0x80004005, 0x80070490):
        assert advice(code) is not None, f"{code:#010x} is not covered"


# ---- surfaced where someone asks ----------------------------------------

from modules.log_viewer.error_lookup_dialog import ErrorLookupDialog  # noqa: E402


def test_the_lookup_shows_the_cause_and_the_remedy(qapp):
    dialog = ErrorLookupDialog()
    try:
        text = dialog.look_up("failed [HRESULT = 0x800F081F]")
        assert "component store has no source" in text
        assert "DISM" in text
    finally:
        dialog.deleteLater()


def test_the_lookup_still_names_a_code_it_has_no_advice_for(qapp):
    dialog = ErrorLookupDialog()
    try:
        text = dialog.look_up("0x80070005")
        assert "0x80070005" in text
        assert "access is denied" in text.lower()
    finally:
        dialog.deleteLater()


def test_the_lookup_invents_nothing_for_an_unknown_code(qapp):
    dialog = ErrorLookupDialog()
    try:
        text = dialog.look_up("0x12345678")
        assert "not a code this tool knows" in text
        assert "DISM" not in text
    finally:
        dialog.deleteLater()
