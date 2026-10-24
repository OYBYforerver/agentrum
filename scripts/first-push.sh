#!/usr/bin/env bash
# 首次发布:创建 GitHub 仓库并推送 Agentrum v0.0.1
#
# 前置(二选一):
#   a) 安装 GitHub CLI 并登录(推荐,HTTPS 凭据自动配置):
#        brew install gh && gh auth login
#   b) 或在 github.com 网页上手动创建空仓库(不要加 README),并配好凭据:
#        - SSH:本机生成密钥并上传公钥(https://github.com/settings/keys)
#        - HTTPS:用 Personal Access Token 作为密码(https://github.com/settings/tokens)
#
# 用法:
#   ./scripts/first-push.sh <github用户名或组织名> [repo名,默认 agentrum] [private]
#
# 示例:
#   ./scripts/first-push.sh oyby            # 公开仓库 github.com/oyby/agentrum
#   ./scripts/first-push.sh agentrum agentrum private
set -euo pipefail

OWNER="${1:?用法: ./scripts/first-push.sh <owner> [repo] [private]}"
REPO="${2:-agentrum}"
VIS="${3:-public}"
REMOTE="git@github.com:${OWNER}/${REPO}.git"
HTTPS_REMOTE="https://github.com/${OWNER}/${REPO}.git"

cd "$(dirname "$0")/.."

GH_OK=false
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  GH_OK=true
fi

echo "==> 目标仓库: ${HTTPS_REMOTE} (${VIS})"

# 1) 创建仓库(gh 可用时);否则请先在网页创建空仓库
if $GH_OK; then
  gh repo create "${OWNER}/${REPO}" --${VIS} --description \
    "Multi-tenant registry for AI agents, MCP servers, skills and prompts" || true
  gh auth setup-git >/dev/null   # git 的 HTTPS 推送走 gh 凭据
else
  echo "!! 未检测到 gh 登录——请先在 https://github.com/new 创建空仓库 ${OWNER}/${REPO}"
  read -rp "创建好了按回车继续…"
fi

# 2) 推送代码(gh 在手走 HTTPS;否则优先 SSH,失败时提示改用 HTTPS)
git remote remove origin 2>/dev/null || true
if $GH_OK; then
  git remote add origin "${HTTPS_REMOTE}"
else
  if ls "${HOME}"/.ssh/*.pub >/dev/null 2>&1; then
    git remote add origin "${REMOTE}"
  else
    git remote add origin "${HTTPS_REMOTE}"
    echo "!! 本机没有 SSH 密钥,已选 HTTPS 远程——推送时会要求输入 GitHub 用户名 + Personal Access Token"
  fi
fi
git push -u origin HEAD:main

# 3) 打 v0.0.1 标签并推送 → 触发发布流水线(ghcr 镜像 + cosign + helm chart)
git tag -fa v0.0.1 -m "Agentrum v0.0.1 — first public release"
git push origin v0.0.1

echo "==> 完成。Actions 会自动跑 CI;tag 触发的 Release 流水线产出 ghcr 镜像与 Helm chart。"
echo "    若首次 Release 失败,到仓库 Settings → Actions → General 打开 workflow 权限后重跑。"
