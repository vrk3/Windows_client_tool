"""The certificate reader's failure path must not fail itself.

`except Exception as e: logger.warning(..., store, e)` referenced a name
that does not exist in fetch_certs — the parameter is `store_name`. So
every PowerShell failure, every malformed JSON payload, raised NameError
from inside the handler meant to report it, and the real reason was lost.
The pane runs this on a Worker, so what reached the user was
"name 'store' is not defined".

Found by ruff (F821) the first time it was run over this tree.
"""
import json
import subprocess

from modules.certificate_viewer import cert_reader


def test_a_failed_enumeration_returns_empty_and_says_why(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise subprocess.SubprocessError("powershell is not on PATH")

    monkeypatch.setattr(cert_reader.subprocess, "run", boom)

    with caplog.at_level("WARNING"):
        result = cert_reader.fetch_certs("ROOT", "machine")

    assert result == []
    assert "powershell is not on PATH" in caplog.text
    assert "ROOT" in caplog.text, "the log must name the store that failed"


def test_malformed_json_is_reported_not_raised(monkeypatch, caplog):
    class _Proc:
        stdout = "{not json at all"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(cert_reader.subprocess, "run", lambda *a, **k: _Proc())

    with caplog.at_level("WARNING"):
        result = cert_reader.fetch_certs("MY", "user")

    assert result == []
    assert "MY" in caplog.text
