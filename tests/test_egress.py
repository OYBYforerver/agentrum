"""Egress guard: publishers must not be able to aim the registry's own
outbound requests (git fetch, health probes, content delivery) at itself,
in-cluster services or cloud metadata endpoints."""

import pytest

from agentrum import errors
from agentrum.config import get_settings
from agentrum.services import egress


@pytest.fixture
def strict_defaults(monkeypatch):
    """Explicit default posture, independent of the developer's .env."""
    s = get_settings()
    monkeypatch.setattr(s, "egress_allow_loopback", False)
    monkeypatch.setattr(s, "egress_allow_private_addresses", True)
    monkeypatch.setattr(s, "egress_allow_file_sources", False)


def test_schemes(strict_defaults, monkeypatch):
    monkeypatch.setattr(
        egress.socket, "getaddrinfo",
        lambda host, port: [(2, 0, 0, "", ("93.184.216.34", 0))],
    )
    assert egress.validate_outbound_url("https://git.corp.example/acme/repo.git")
    assert egress.validate_outbound_url("http://git.corp.example/acme/repo.git")
    assert egress.validate_outbound_url("git://git.corp.example/acme/repo.git")
    for bad in ("file:///etc/repo", "/etc/repo", "ssh://git@host/repo", "ftp://host/repo", "gopher://host"):
        with pytest.raises(errors.ValidationError):
            egress.validate_outbound_url(bad)


def test_file_sources_need_explicit_opt_in(monkeypatch, strict_defaults):
    s = get_settings()
    with pytest.raises(errors.ValidationError):
        egress.validate_outbound_url("file:///tmp/skills-repo")
    monkeypatch.setattr(s, "egress_allow_file_sources", True)
    assert egress.validate_outbound_url("file:///tmp/skills-repo")


def test_loopback_and_metadata_blocked(strict_defaults):
    for bad in (
        "http://127.0.0.1:8080/mcp",
        "http://[::1]:8080/mcp",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://0.0.0.0:12122/v1/resources",
    ):
        with pytest.raises(errors.ValidationError):
            egress.validate_outbound_url(bad)


def test_loopback_dev_escape_hatch(monkeypatch, strict_defaults):
    s = get_settings()
    monkeypatch.setattr(s, "egress_allow_loopback", True)
    assert egress.validate_outbound_url("http://127.0.0.1:8080/mcp")
    assert egress.validate_outbound_url("http://169.254.169.254/latest/meta-data/")


def test_private_addresses_allowed_by_default_deniable(monkeypatch, strict_defaults):
    s = get_settings()
    assert egress.validate_outbound_url("http://10.1.2.3:3000/mcp")
    assert egress.validate_outbound_url("https://192.168.1.10/git/repo.git")
    monkeypatch.setattr(s, "egress_allow_private_addresses", False)
    with pytest.raises(errors.ValidationError):
        egress.validate_outbound_url("http://10.1.2.3:3000/mcp")


def test_hostname_resolving_to_loopback_is_blocked(strict_defaults, monkeypatch):
    monkeypatch.setattr(
        egress.socket, "getaddrinfo",
        lambda host, port: [(2, 0, 0, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(errors.ValidationError):
        egress.validate_outbound_url("http://localhost:8000/mcp")


def test_hostname_resolving_to_public_address_passes(strict_defaults, monkeypatch):
    monkeypatch.setattr(
        egress.socket, "getaddrinfo",
        lambda host, port: [
            (2, 0, 0, "", ("140.82.121.4", 0)),
            (10, 0, 0, "", ("140.82.121.4", 0, 0, 0)),
        ],
    )
    assert egress.validate_outbound_url("git://github.com/acme/repo.git")


def test_unresolvable_host_rejected(strict_defaults, monkeypatch):
    def boom(host, port):
        raise OSError("no dns")

    monkeypatch.setattr(egress.socket, "getaddrinfo", boom)
    with pytest.raises(errors.ValidationError):
        egress.validate_outbound_url("https://nonexistent.invalid/repo.git")
