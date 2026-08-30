"""The two dialogs. Both are shells over logic that is tested elsewhere."""
from modules.log_viewer.error_lookup_dialog import ErrorLookupDialog
from modules.log_viewer.highlight_dialog import HighlightDialog
from modules.log_viewer.highlight import HighlightRule


def test_looking_up_a_bare_code_explains_it(qapp):
    dialog = ErrorLookupDialog()
    try:
        assert "denied" in dialog.look_up("0x80070005").lower()
    finally:
        dialog.close()


def test_looking_up_a_whole_pasted_line_finds_the_code_in_it(qapp):
    dialog = ErrorLookupDialog()
    try:
        answer = dialog.look_up("Failed [HRESULT = 0x80070005 - E_DENIED]")
        assert "0x80070005" in answer
    finally:
        dialog.close()


def test_a_code_nobody_knows_says_so_rather_than_guessing(qapp):
    dialog = ErrorLookupDialog()
    try:
        answer = dialog.look_up("0x0ABCDEF1")
        assert "not" in answer.lower() or "unknown" in answer.lower()
    finally:
        dialog.close()


def test_text_with_no_code_at_all_says_so(qapp):
    dialog = ErrorLookupDialog()
    try:
        assert "no " in dialog.look_up("nothing here").lower()
    finally:
        dialog.close()


def test_the_highlight_editor_returns_the_rules_it_was_given(qapp):
    rules = [HighlightRule("boom", "#ff0000")]
    dialog = HighlightDialog(rules)
    try:
        assert dialog.rules() == rules
    finally:
        dialog.close()


def test_adding_a_rule_in_the_editor(qapp):
    dialog = HighlightDialog([])
    try:
        dialog.add_rule(HighlightRule("new", "#00ff00", regex=True))
        assert dialog.rules() == [HighlightRule("new", "#00ff00", regex=True)]
    finally:
        dialog.close()


def test_an_invalid_pattern_is_flagged_rather_than_rejected(qapp):
    """Half a regex is a work in progress, not an error to refuse."""
    dialog = HighlightDialog([])
    try:
        dialog.add_rule(HighlightRule("[unclosed", "#00ff00", regex=True))
        assert dialog.invalid_rows() == [0]
        assert len(dialog.rules()) == 1
    finally:
        dialog.close()
