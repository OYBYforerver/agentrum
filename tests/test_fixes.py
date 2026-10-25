"""Unit tests for the security fixes: git ref resolution, credential
redaction, image allowlist boundaries, condition merge semantics,
deployment spec hardening."""

import pytest

from agentrum import errors
from agentrum.schemas.specs import validate_spec
from agentrum.services.conditions import merge_condition
from agentrum.services.deployments.allowlist import image_allowed
from agentrum.services.deployments.reconciler import _condition
from agentrum.services.git_service import _pick_ref, redact

# --- git ref resolution -------------------------------------------------------

def _refs() -> dict:
    return {
        b"HEAD": b"1" * 40,
        b"refs/heads/main": b"2" * 40,
        b"refs/tags/v1.0": b"3" * 40,  # annotated tag object
        b"refs/tags/v1.0^{}": b"4" * 40,  # peeled commit
    }


def test_pick_ref_resolves_branch():
    assert _pick_ref(_refs(), "main") == b"2" * 40


def test_pick_ref_prefers_peeled_tag():
    assert _pick_ref(_refs(), "v1.0") == b"4" * 40


def test_pick_ref_never_falls_back_to_head():
    """A misspelled ref must fail, not silently pin HEAD."""
    assert _pick_ref(_refs(), "mainx") is None


def test_pick_ref_head_only_when_asked():
    assert _pick_ref(_refs(), "HEAD") == b"1" * 40


def test_redact_strips_url_credentials():
    text = "cannot resolve git ref: https://ci-bot:hunter2@git.internal/acme/repo.git: 401"
    assert "hunter2" not in redact(text)
    assert "git.internal" in redact(text)


# --- image allowlist ----------------------------------------------------------

def test_allowlist_host_prefix_is_a_boundary():
    allowlist = ["registry.internal"]
    assert image_allowed("registry.internal/team/app:v1", allowlist)
    assert not image_allowed("registry.internal-evil/app:v1", allowlist)


def test_allowlist_path_prefix():
    allowlist = ["registry.internal/team/"]
    assert image_allowed("registry.internal/team/app:v1", allowlist)
    assert not image_allowed("registry.internal/other/app:v1", allowlist)


def test_allowlist_empty_is_permissive():
    assert image_allowed("docker.io/anything", [])


# --- condition merge semantics -------------------------------------------------

class _Row:
    """Minimal stand-in for models.Resource (status dict only)."""

    def __init__(self, status=None):
        self.status = status


def test_merge_condition_preserves_other_types():
    row = _Row({"conditions": [{"type": "UpstreamDrift", "status": "True"}]})
    changed = merge_condition(row, _condition(True, "applied"))
    types = [c["type"] for c in row.status["conditions"]]
    assert changed is True
    assert "UpstreamDrift" in types and "Ready" in types


def test_merge_condition_upserts_same_type():
    row = _Row({"conditions": [{"type": "Ready", "status": "False", "message": "down"}]})
    merge_condition(row, _condition(True, "up"))
    ready = [c for c in row.status["conditions"] if c["type"] == "Ready"]
    assert len(ready) == 1 and ready[0]["message"] == "up"


def test_merge_condition_ignores_volatile_timestamps():
    row = _Row({"conditions": [_condition(True, "applied")]})
    again = _condition(True, "applied")  # fresh last_transition
    assert merge_condition(row, again) is False
    assert merge_condition(row, _condition(True, "changed message")) is True


# --- deployment spec hardening -----------------------------------------------

def test_deployment_spec_rejects_reserved_cluster_namespace():
    with pytest.raises(errors.ValidationError):
        validate_spec("Deployment", {
            "target_kind": "Agent", "target_namespace": "ns", "target_name": "a",
            "cluster_namespace": "kube-system",
        })


def test_deployment_spec_rejects_bad_replicas_and_port():
    with pytest.raises(errors.ValidationError):
        validate_spec("Deployment", {
            "target_kind": "Agent", "target_namespace": "ns", "target_name": "a",
            "replicas": 0,
        })
    with pytest.raises(errors.ValidationError):
        validate_spec("Deployment", {
            "target_kind": "Agent", "target_namespace": "ns", "target_name": "a",
            "port": 70000,
        })


def test_agent_spec_rejects_url_as_image():
    with pytest.raises(errors.ValidationError):
        validate_spec("Agent", {"image": "https://evil.example/agent:latest"})


def test_agent_spec_accepts_normal_image():
    spec = validate_spec("Agent", {"image": "registry.internal/team/agent:1.2.3"})
    assert spec["image"] == "registry.internal/team/agent:1.2.3"


# --- skill content delivery ---------------------------------------------------

def test_subdirectory_validation_blocks_traversal():
    import pytest

    from agentrum.services.skill_content_service import _validate_subdirectory

    assert _validate_subdirectory(None) == []
    assert _validate_subdirectory("") == []
    assert _validate_subdirectory("pack/gateway") == ["pack", "gateway"]
    assert _validate_subdirectory("./pack/../pack/gateway") == ["pack", "gateway"]
    for bad in ("..", "../escape", "a/../../escape", "/absolute", "//double"):
        with pytest.raises(errors.ValidationError):
            _validate_subdirectory(bad)


# --- agent endpoint delivery ---------------------------------------------------

def test_service_url_writeback_shape():
    from agentrum.services.deployments.adapter import DeploymentPlan, _service_url

    plan = DeploymentPlan(
        name="pay-agent", cluster_namespace="agents", image="i:v1",
        env={}, replicas=1, port=8000,
    )
    assert _service_url(plan) == "http://pay-agent.agents.svc:8000"
