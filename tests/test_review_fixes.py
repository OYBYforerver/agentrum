"""Unit tests for the code-review fixes: socket-timeout hygiene, the skill
content disk cache, deployment hardening fields, and spec passthrough."""

import socket
import time
from typing import ClassVar

import pytest

from agentrum import errors
from agentrum.schemas.specs import validate_spec
from agentrum.services import skill_content_service
from agentrum.services.deployments.adapter import (
    DeploymentPlan,
    KubernetesAdapter,
    build_container,
    build_pod_spec,
)
from agentrum.services.deployments.reconciler import _plan_from
from agentrum.services.git_service import _socket_timeout

# --- git socket timeout ---------------------------------------------------------


def test_socket_timeout_restores_previous_value():
    before = socket.getdefaulttimeout()
    with _socket_timeout(30):
        assert socket.getdefaulttimeout() == 30
    assert socket.getdefaulttimeout() == before


def test_socket_timeout_restores_on_exception():
    before = socket.getdefaulttimeout()
    with pytest.raises(RuntimeError), _socket_timeout(30):
        raise RuntimeError("fetch blew up")
    assert socket.getdefaulttimeout() == before


def test_socket_timeout_concurrent_threads_cannot_leak():
    """Concurrent windows serialize on the lock; when the dust settles the
    process default is exactly what it was before."""
    import threading

    before = socket.getdefaulttimeout()
    done = []

    def worker():
        with _socket_timeout(30):
            time.sleep(0.01)
        done.append(socket.getdefaulttimeout())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(done) == 4
    assert socket.getdefaulttimeout() == before


# --- skill content cache --------------------------------------------------------


class _Res:
    namespace = "team"


class _Ver:
    spec: ClassVar[dict] = {
        "source": {"git": {"url": "file:///nowhere/repo", "resolved_sha": "a" * 40}}
    }


def _fake_builder(monkeypatch, payload=b"tarball-bytes"):
    calls = {"n": 0}

    def build(url, sha, subdirectory, creds, max_bytes):
        calls["n"] += 1
        return payload

    monkeypatch.setattr(skill_content_service, "_build_tarball_sync", build)
    return calls


async def _no_creds(monkeypatch):
    from agentrum.services import egress, git_service

    monkeypatch.setattr(egress, "validate_outbound_url", lambda *a, **k: a[0])

    async def _creds(*args, **kwargs):
        return None

    monkeypatch.setattr(git_service, "_credentials_for", _creds)


async def test_build_tarball_caches_by_url_and_sha(monkeypatch, tmp_path):
    await _no_creds(monkeypatch)
    monkeypatch.setattr(skill_content_service, "_CACHE_DIR", tmp_path)
    calls = _fake_builder(monkeypatch)

    first, sha = await skill_content_service.build_tarball(None, _Res(), _Ver())
    second, _ = await skill_content_service.build_tarball(None, _Res(), _Ver())
    assert first == b"tarball-bytes" and sha == "a" * 40
    assert second == first
    assert calls["n"] == 1  # second call served from the cache


async def test_build_tarball_cache_disabled_rebuilds(monkeypatch, tmp_path):
    await _no_creds(monkeypatch)
    monkeypatch.setattr(skill_content_service, "_CACHE_DIR", tmp_path)
    calls = _fake_builder(monkeypatch)

    class _S:  # TTL 0 disables the cache
        skill_content_cache_seconds = 0
        skill_content_max_bytes = 1024
        git_timeout_seconds = 5

    monkeypatch.setattr(skill_content_service, "get_settings", lambda: _S())
    await skill_content_service.build_tarball(None, _Res(), _Ver())
    await skill_content_service.build_tarball(None, _Res(), _Ver())
    assert calls["n"] == 2  # no cache → every download rebuilds


def test_cache_prune_evicts_oldest(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr(skill_content_service, "_CACHE_DIR", tmp_path)
    for i in range(3):
        p = tmp_path / f"{i}.tar.gz"
        p.write_bytes(b"x" * 10)
        stamp = time.time() - 100 * (3 - i)  # 0 oldest, 2 newest
        os.utime(p, (stamp, stamp))
    # total 30 bytes vs a 25-byte cap: only the oldest file has to go
    monkeypatch.setattr(skill_content_service, "_CACHE_MAX_TOTAL_BYTES", 25)
    skill_content_service._prune_cache()
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["1.tar.gz", "2.tar.gz"]  # the oldest was evicted


# --- deployment hardening -------------------------------------------------------


def test_deployment_spec_accepts_run_as_non_root():
    spec = validate_spec(
        "Deployment",
        {
            "target_kind": "Agent",
            "target_namespace": "ns",
            "target_name": "a",
            "run_as_non_root": True,
        },
    )
    assert spec["run_as_non_root"] is True


def test_plan_from_passes_run_as_non_root():
    plan = _plan_from(
        type("R", (), {"namespace": "ns", "name": "a"})(),
        {"run_as_non_root": True},
        image="i:v1",
        env={},
    )
    assert plan["run_as_non_root"] is True


def test_container_hardening_is_unconditional():
    plan = DeploymentPlan(
        name="app",
        cluster_namespace="ns",
        image="i:v1",
        env={},
        replicas=1,
        port=8000,
    )
    c = build_container(plan, env_secret=None)
    assert c.security_context.allow_privilege_escalation is False
    assert c.security_context.capabilities.drop == ["ALL"]
    pod = build_pod_spec(plan, c)
    assert pod.security_context.seccomp_profile.type == "RuntimeDefault"
    assert pod.security_context.run_as_non_root is None  # opt-in only


def test_pod_spec_honors_run_as_non_root_opt_in():
    plan = DeploymentPlan(
        name="app",
        cluster_namespace="ns",
        image="i:v1",
        env={},
        replicas=1,
        port=8000,
        run_as_non_root=True,
    )
    pod = build_pod_spec(plan, build_container(plan, None))
    assert pod.security_context.run_as_non_root is True


def test_validate_spec_still_rejects_bad_deployment():
    with pytest.raises(errors.ValidationError):
        validate_spec(
            "Deployment", {"target_kind": "Skill", "target_namespace": "n", "target_name": "x"}
        )


# --- kubernetes adapter config -------------------------------------------------


async def test_incluster_config_is_not_awaited(monkeypatch):
    from kubernetes_asyncio import config as kube_config

    calls: list[str] = []

    async def fake_kube_config(**kwargs):
        calls.append("kubeconfig")

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    monkeypatch.setattr(kube_config, "load_incluster_config", lambda: calls.append("incluster"))
    monkeypatch.setattr(kube_config, "load_kube_config", fake_kube_config)

    await KubernetesAdapter()._ensure_config()

    assert calls == ["incluster"]
