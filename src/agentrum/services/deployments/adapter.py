"""Deployment adapter interface + native Kubernetes adapter.

The controller is runtime-agnostic: `DeploymentAdapter` is the seam.
`KubernetesAdapter` creates/updates a Deployment + Service in the target
cluster namespace using kubernetes-asyncio (in-cluster config when running
inside K8s, otherwise the local kubeconfig).

Resolved secret env values are written to a dedicated Kubernetes Secret and
injected via envFrom — the values never appear in the (world-readable)
Deployment spec.
"""

import base64
import hashlib
import logging
from datetime import UTC, datetime
from typing import Protocol

logger = logging.getLogger("agentrum.deploy")


class DeploymentPlan(dict):
    """Computed desired state for one Deployment resource row."""

    @property
    def name(self) -> str:
        return self["name"]

    @property
    def cluster_namespace(self) -> str:
        return self["cluster_namespace"]


class DeploymentAdapter(Protocol):
    async def apply(self, plan: DeploymentPlan) -> dict:  # returns a Ready condition
        ...

    async def remove(self, plan: DeploymentPlan) -> dict:
        ...


def _condition(ok: bool, message: str, reason: str = "Reconciled", **extra) -> dict:
    cond = {
        "type": "Ready",
        "status": "True" if ok else "False",
        "reason": reason,
        "message": message,
        "last_transition": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    cond.update(extra)
    return cond


def _service_url(plan: DeploymentPlan) -> str:
    """Cluster-internal DNS for the reconciled Service."""
    return f"http://{plan.name}.{plan.cluster_namespace}.svc:{plan.get('port', 8000)}"


def _container_name(plan_name: str) -> str:
    """Container names cap at 63 chars; long registry names keep uniqueness
    via a short hash instead of failing reconciliation forever."""
    if len(plan_name) <= 63:
        return plan_name
    suffix = hashlib.sha1(plan_name.encode()).hexdigest()[:8]
    return f"{plan_name[:54]}-{suffix}"


def _secret_name(plan_name: str) -> str:
    return f"{_container_name(plan_name)}-env"


def build_container(plan: DeploymentPlan, env_secret: str | None):
    """Container for one plan. Baseline hardening is unconditional
    (no privilege escalation, all capabilities dropped) — safe for any
    image; runAsNonRoot is opt-in via the spec since root-based images
    would otherwise fail to start."""
    from kubernetes_asyncio import client

    return client.V1Container(
        name=_container_name(plan["name"]),
        image=plan["image"],
        image_pull_policy=plan.get("image_pull_policy", "IfNotPresent"),
        env_from=(
            [client.V1EnvFromSource(secret_ref=client.V1SecretEnvSource(name=env_secret))]
            if env_secret
            else None
        ),
        ports=[client.V1ContainerPort(container_port=plan.get("port", 8000))],
        security_context=client.V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        ),
    )


def build_pod_spec(plan: DeploymentPlan, container):
    from kubernetes_asyncio import client

    return client.V1PodSpec(
        containers=[container],
        service_account_name=plan.get("service_account") or None,
        security_context=client.V1PodSecurityContext(
            run_as_non_root=plan.get("run_as_non_root") or None,
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
        ),
    )


class KubernetesAdapter:
    """Native Kubernetes runtime (no kagent dependency)."""

    def __init__(self) -> None:
        self._loaded = False

    async def _ensure_config(self) -> None:
        if self._loaded:
            return
        import os

        from kubernetes_asyncio import config

        # load_incluster_config is synchronous in kubernetes_asyncio; only the
        # kubeconfig loader is a coroutine.
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            config.load_incluster_config()
        else:
            await config.load_kube_config()
        self._loaded = True

    def _labels(self, plan: DeploymentPlan) -> dict[str, str]:
        return {
            "app.kubernetes.io/managed-by": "agentrum",
            "app.kubernetes.io/name": plan["name"],
        }

    async def _apply_env_secret(self, core, plan: DeploymentPlan) -> str | None:
        """Write resolved env values to a dedicated K8s Secret. Returns the
        secret name, or None when there is nothing to inject."""
        from kubernetes_asyncio import client

        env = plan.get("env") or {}
        if not env:
            return None
        name = _secret_name(plan["name"])
        body = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=name, namespace=plan["cluster_namespace"], labels=self._labels(plan)
            ),
            data={k: base64.b64encode(str(v).encode()).decode() for k, v in env.items()},
        )
        try:
            await core.patch_namespaced_secret(name, plan["cluster_namespace"], body)
        except client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise
            await core.create_namespaced_secret(plan["cluster_namespace"], body)
        return name

    async def apply(self, plan: DeploymentPlan) -> dict:
        await self._ensure_config()
        from kubernetes_asyncio import client

        apps = client.AppsV1Api()
        core = client.CoreV1Api()
        labels = self._labels(plan)
        selector = {"matchLabels": {"app.kubernetes.io/name": plan["name"]}}
        env_secret = await self._apply_env_secret(core, plan)
        container = build_container(plan, env_secret)
        pod_spec = build_pod_spec(plan, container)
        body = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=plan["name"], namespace=plan["cluster_namespace"], labels=labels
            ),
            spec=client.V1DeploymentSpec(
                replicas=plan.get("replicas", 1),
                selector=selector,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=labels), spec=pod_spec
                ),
            ),
        )
        try:
            await apps.patch_namespaced_deployment(
                plan["name"], plan["cluster_namespace"], body
            )
        except client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise
            await apps.create_namespaced_deployment(plan["cluster_namespace"], body)

        svc = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=plan["name"], namespace=plan["cluster_namespace"], labels=labels
            ),
            spec=client.V1ServiceSpec(
                selector={"app.kubernetes.io/name": plan["name"]},
                ports=[client.V1ServicePort(port=plan.get("port", 8000))],
            ),
        )
        try:
            await core.patch_namespaced_service(plan["name"], plan["cluster_namespace"], svc)
        except client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise
            await core.create_namespaced_service(plan["cluster_namespace"], svc)

        # Report actual rollout progress instead of a fabricated success.
        ready = replicas = 0
        try:
            dep = await apps.read_namespaced_deployment(
                plan["name"], plan["cluster_namespace"]
            )
            status = dep.status
            replicas = dep.spec.replicas or 0
            ready = min(status.ready_replicas or 0, replicas)
        except Exception:  # noqa: BLE001 - status is best-effort
            ready = replicas = -1
        url = _service_url(plan)
        if ready < 0:
            return _condition(
                True,
                f"applied {plan['image']} to {plan['cluster_namespace']}/{plan['name']}; service at {url}",
                reason="Applied",
                service_url=url,
            )
        if ready >= replicas > 0:
            return _condition(
                True,
                f"applied {plan['image']} to {plan['cluster_namespace']}/{plan['name']} "
                f"({ready}/{replicas} ready); service at {url}",
                service_url=url,
            )
        return _condition(
            False,
            f"rollout in progress ({max(ready, 0)}/{replicas} ready); service at {url}",
            reason="Progressing",
            service_url=url,
        )

    async def remove(self, plan: DeploymentPlan) -> dict:
        await self._ensure_config()
        from kubernetes_asyncio import client

        apps = client.AppsV1Api()
        core = client.CoreV1Api()
        for delete_fn, args in (
            (apps.delete_namespaced_deployment, (plan["name"], plan["cluster_namespace"])),
            (core.delete_namespaced_service, (plan["name"], plan["cluster_namespace"])),
            (core.delete_namespaced_secret, (_secret_name(plan["name"]), plan["cluster_namespace"])),
        ):
            try:
                await delete_fn(*args)
            except client.exceptions.ApiException as exc:
                if exc.status != 404:
                    raise
        return _condition(True, "removed from cluster", reason="Removed")


def get_adapter(name: str = "kubernetes") -> DeploymentAdapter:
    """Adapter registry — new runtimes plug in here."""
    if name == "kubernetes":
        return KubernetesAdapter()
    raise ValueError(f"unknown deployment runtime {name!r}")
