# tests/test_virustotal_client.py
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
from modules.process_explorer.virustotal_client import (
    compute_sha256, VTResult, check_hash, VTClient,
)


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert compute_sha256(str(f)) == expected


def test_compute_sha256_missing_file():
    result = compute_sha256("/nonexistent/path/file.exe")
    assert result is None


def test_check_hash_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"attributes": {"last_analysis_stats": {"malicious": 3, "undetected": 69}}}
    }
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp):
        result = check_hash("abc123", api_key="testkey")
    assert result.found is True
    assert result.malicious == 3
    assert result.total == 72
    assert result.score == "3/72"


def test_check_hash_not_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp):
        result = check_hash("abc123", api_key="testkey")
    assert result.found is False
    assert result.score is None


def test_vt_client_caches_result():
    client = VTClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"attributes": {"last_analysis_stats": {"malicious": 0, "undetected": 72}}}
    }
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp) as m:
        r1 = client.check("abc123")
        r2 = client.check("abc123")  # second call should use cache
    assert m.call_count == 1  # only one HTTP call
    assert r1.score == r2.score


def test_submit_file_returns_analysis_id(tmp_path):
    f = tmp_path / "sample.bin"
    f.write_bytes(b"data")
    client = VTClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "analysis-xyz"}}
    with patch("modules.process_explorer.virustotal_client.requests.post", return_value=mock_resp):
        result = client.submit_file(str(f), sha256="deadbeef")
    assert result == "analysis-xyz"
    assert client._pending.get("analysis-xyz") == "deadbeef"


def test_poll_analysis_pending_returns_none():
    client = VTClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {"attributes": {"status": "queued", "stats": {}}, "meta": {}}
    }
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp):
        result = client.poll_analysis("analysis-xyz")
    assert result is None


def test_poll_analysis_completed_caches_result():
    client = VTClient(api_key="testkey")
    client._pending["analysis-xyz"] = "deadbeef"
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "attributes": {"status": "completed", "stats": {"malicious": 1, "undetected": 71}},
            "meta": {},
        }
    }
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp):
        result = client.poll_analysis("analysis-xyz")
    assert result is not None
    assert result.sha256 == "deadbeef"
    assert result.score == "1/72"
    assert "deadbeef" in client._cache
