# --- UI builder: static console export (Next.js output: 'export' -> ui/out) ---
FROM node:22-alpine AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui ./
RUN npm run build

# --- docs builder: bilingual handbook (mkdocs) ---
FROM python:3.12-slim AS docs
RUN pip install --no-cache-dir \
    "mkdocs-material==9.8.0" \
    "mkdocs-static-i18n==1.3.1"
COPY mkdocs.yml ./
COPY docs/site ./docs/site
RUN mkdocs build -d /built

# --- runtime ---
FROM python:3.12-slim

# Pin uv to the version uv.lock was generated with (never float on latest).
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# bundle the handbook and serve it at /handbook
COPY --from=docs /built /app/handbook
ENV ARK_DOCS_DIR=/app/handbook

# bundle the static console (served by the backend when ARK_UI_DIR is set)
COPY --from=ui /src/ui/out /app/ui-out
ENV ARK_UI_DIR=/app/ui-out

# never run as root
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin agentrum \
    && chown -R agentrum:agentrum /app
# Numeric user: kubelet cannot verify a named user under runAsNonRoot.
USER 10001:10001

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["uvicorn", "agentrum.main:app", "--host", "0.0.0.0", "--port", "8080"]
