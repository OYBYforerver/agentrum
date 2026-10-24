# Deploy to Kubernetes

The Agentrum deployment controller treats `Deployment` resources as **desired state** and reconciles them level-triggered into the target cluster using a native Kubernetes adapter (no kagent dependency).

## Publish a deployment

```yaml
kind: Deployment
metadata: {name: fraud-detection-prod, namespace: payment}
spec:
  target_kind: Agent
  target_namespace: payment
  target_name: fraud-detection
  tag: v1.0.0            # optional: pin a tag; default follows latest
  cluster_namespace: agents
  replicas: 2
  port: 8000
  image_pull_policy: IfNotPresent
```

The controller resolves the target's image → enforces `ARK_IMAGE_ALLOWLIST` → resolves `env.secretRef` credentials → creates/updates a Deployment + Service in the cluster → writes the outcome back into `status.conditions`.

## Image allowlist (required in production)

Publish rights ≈ code-execution rights, so what may run in the cluster must be controlled:

```bash
ARK_IMAGE_ALLOWLIST=registry.internal/,ghcr.io/acme/
```

Images outside the allowlist never reach the cluster; the Deployment shows an `ImageNotAllowed` condition instead.

## Observing status

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  $SERVER/v1/resources/Deployment/payment/fraud-detection-prod | jq .status
```

Conditions carry `reason` (`Reconciled / TargetMissing / NoImage / ImageNotAllowed / EnvResolutionFailed / AdapterError`). Soft-deleting the Deployment resource makes the controller clean up the workload.

## Cluster-side setup

- In-cluster config is used automatically when the controller runs inside K8s; local dev falls back to kubeconfig
- RBAC is namespace-scoped least-privilege (`charts/agentrum/templates/serviceaccount.yaml`): only Deployment/Service CRUD, only in the controller's namespace
- Reconcile interval: `ARK_DEPLOY_INTERVAL_SECONDS` (default 10s)

!!! note "Credentials in deployments"
    Secrets referenced via `env.secret_ref` are resolved by Agentrum at reconcile time and injected as container env vars; the values stay envelope-encrypted in the database and are never returned by the API.
