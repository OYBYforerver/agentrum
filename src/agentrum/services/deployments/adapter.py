"""Deployment adapter interface + native Kubernetes adapter.

The controller is runtime-agnostic: `DeploymentAdapter` is the seam.
`KubernetesAdapter` creates/updates a Deployment + Service in the target
cluster namespace using kubernetes-asyncio (in-cluster config when running
inside K8s, otherwise the local kubeconfig).
"""

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


class KubernetesAdapter:
    """Native Kubernetes runtime (no kagent dependency)."""

    def __init__(self) -> None:
        self._loaded = False

    async def _ensure_config(self) -> None:
        if self._loaded:
            return
        import os

        from kubernetes_asyncio import config

        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            await config.load_incluster_config()
        else:
            await config.load_kube_config()
        self._loaded = True

    def _labels(self, plan: DeploymentPlan) -> dict[str, str]:
        return {
            "app.kubernetes.io/managed-by": "agentrum",
            "app.kubernetes.io/name": plan["name"],
        }

    async def apply(self, plan: DeploymentPlan) -> dict:
        await self._ensure_config()
        from kubernetes_asyncio import client

        apps = client.AppsV1Api()
        core = client.CoreV1Api()
        labels = self._labels(plan)
        selector = {"matchLabels": {"app.kubernetes.io/name": plan["name"]}}
        container = client.V1Container(
            name=plan["name"],
            image=plan["image"],
            image_pull_policy=plan.get("image_pull_policy", "IfNotPresent"),
            env=[
                client.V1EnvVar(name=k, value=v) for k, v in (plan.get("env") or {}).items()
            ],
            ports=[client.V1ContainerPort(container_port=plan.get("port", 8000))],
        )
        pod_spec = client.V1PodSpec(
            containers=[container],
            service_account_name=plan.get("service_account") or None,
        )
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

        return self._condition(
            True, f"applied {plan['image']} to {plan['cluster_namespace']}/{plan['name']}"
        )

    async def remove(self, plan: DeploymentPlan) -> dict:
        await self._ensure_config()
        from kubernetes_asyncio import client

        apps = client.AppsV1Api()
        core = client.CoreV1Api()
        for delete_fn, args in (
            (apps.delete_namespaced_deployment, (plan["name"], plan["cluster_namespace"])),
            (core.delete_namespaced_service, (plan["name"], plan["cluster_namespace"])),
        ):
            try:
                await delete_fn(*args)
            except client.exceptions.ApiException as exc:
                if exc.status != 404:
                    raise
        return self._condition(True, "removed from cluster")

    @staticmethod
    def _condition(ok: bool, message: str) -> dict:
        return {
            "type": "Ready",
            "status": "True" if ok else "False",
            "message": message,
            "last_transition": datetime.now(UTC).isoformat(timespec="seconds"),
        }


def _condition(ok: bool, message: str) -> dict:
    return {
        "type": "Ready",
        "status": "True" if ok else "False",
        "message": message,
        "last_transition": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def get_adapter(name: str = "kubernetes") -> DeploymentAdapter:
    """Adapter registry — new runtimes plug in here."""
    if name == "kubernetes":
        return KubernetesAdapter()
    raise ValueError(f"unknown deployment runtime {name!r}")
