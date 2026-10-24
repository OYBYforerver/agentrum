# 部署接入(Kubernetes)

Agentrum 的部署控制器把 `Deployment` 资源当作**期望状态**,级别触发地调和到目标集群——使用原生 Kubernetes 适配器(不依赖 kagent)。

## 发布一个部署

```yaml
kind: Deployment
metadata: {name: fraud-detection-prod, namespace: payment}
spec:
  target_kind: Agent
  target_namespace: payment
  target_name: fraud-detection
  tag: v1.0.0            # 可选:锁定版本 tag;缺省跟随最新
  cluster_namespace: agents
  replicas: 2
  port: 8000
  image_pull_policy: IfNotPresent
```

控制器会:解析目标资源的镜像 → 校验 `ARK_IMAGE_ALLOWLIST` → 解析 `env.secretRef` 凭据 → 在集群内创建/更新 Deployment + Service → 把结果写回资源的 `status.conditions`。

## 镜像白名单(生产必设)

发布权 ≈ 代码执行权,因此集群里能跑什么镜像必须受控:

```bash
ARK_IMAGE_ALLOWLIST=registry.internal/,ghcr.io/acme/
```

不在白名单内的镜像不会下发到集群,Deployment 条目显示 `ImageNotAllowed` 条件。

## 观察状态

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  $SERVER/v1/resources/Deployment/payment/fraud-detection-prod | jq .status
```

条件类型:`Ready`(True/False)+ `reason`(`Reconciled / TargetMissing / NoImage / ImageNotAllowed / EnvResolutionFailed / AdapterError`)。软删除 Deployment 资源会触发控制器清理集群内工作负载。

## 集群侧配置

- 控制器在集群内运行时自动使用 in-cluster 配置;本地开发用 kubeconfig
- ServiceAccount RBAC 按命名空间最小授权(见 `charts/agentrum/templates/serviceaccount.yaml`):仅 Deployment/Service 的增删改查,仅限控制器所在命名空间
- 控制器调和周期:`ARK_DEPLOY_INTERVAL_SECONDS`(默认 10s)

!!! note "部署目标里的凭据"
    `env.secret_ref` 引用的 Secret 资源在调和时由 Agentrum 解出明文注入容器环境变量;Secret 值本身在数据库中信封加密,且永远不会通过 API 返回。
