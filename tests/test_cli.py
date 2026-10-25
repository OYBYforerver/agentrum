"""CLI `configure`: writes the registry MCP entry into client configs,
merging without clobbering existing entries, 0600 on create."""

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentrum.cli import main as cli_main


@pytest.fixture
def stored_ak_sk(tmp_path, monkeypatch):
    cred = tmp_path / "credentials.json"
    cred.write_text(
        json.dumps(
            {"server": "https://registry.internal", "ak": "ark-ak-1", "sk": "ark-sk-2"}
        )
    )
    monkeypatch.setattr(cli_main, "_CREDENTIALS", cred)
    for var in ("AGENTRUM_SERVER", "AGENTRUM_AK", "AGENTRUM_SK", "AGENTRUM_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return cred


def _run(*args):
    return CliRunner().invoke(cli_main.app, ["configure", *args])


def test_configure_generic_prints_snippet(stored_ak_sk):
    result = _run("--client", "generic")
    assert result.exit_code == 0, result.output
    snippet = json.loads(result.output)
    entry = snippet["mcpServers"]["agentrum"]
    assert entry["url"] == "https://registry.internal/mcp"
    assert entry["headers"]["Authorization"].startswith("Basic ")


def test_configure_cursor_writes_and_merges(stored_ak_sk, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    existing = home / ".cursor" / "mcp.json"
    existing.parent.mkdir(parents=True)
    existing.write_text(json.dumps({"mcpServers": {"other": {"url": "http://x"}}}))

    result = _run("--client", "cursor")
    assert result.exit_code == 0, result.output
    data = json.loads(existing.read_text())
    assert data["mcpServers"]["other"] == {"url": "http://x"}  # untouched
    assert data["mcpServers"]["agentrum"]["url"] == "https://registry.internal/mcp"
    # existing file keeps its permissions; mode unchanged is fine


def test_configure_claude_code_creates_private_file(stored_ak_sk, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _run("--client", "claude-code")
    assert result.exit_code == 0, result.output
    written = tmp_path / ".mcp.json"
    data = json.loads(written.read_text())
    entry = data["mcpServers"]["agentrum"]
    assert entry["type"] == "http"
    assert entry["url"] == "https://registry.internal/mcp"
    mode = stat.S_IMODE(written.stat().st_mode)
    assert mode == 0o600  # the file carries credentials


def test_configure_refuses_to_clobber_broken_json(stored_ak_sk, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / ".mcp.json"
    bad.write_text("{not json")
    result = _run("--client", "claude-code")
    assert result.exit_code == 1
    assert bad.read_text() == "{not json"


def test_configure_needs_login(tmp_path, monkeypatch):
    cred = tmp_path / "credentials.json"
    monkeypatch.setattr(cli_main, "_CREDENTIALS", cred)
    for var in ("AGENTRUM_SERVER", "AGENTRUM_AK", "AGENTRUM_SK", "AGENTRUM_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    result = _run("--client", "generic", "--server", "https://r.internal")
    assert result.exit_code == 1
