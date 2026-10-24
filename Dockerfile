# --- docs builder: bilingual handbook (mkdocs) ---
FROM python:3.12-slim AS docs
RUN pip install --no-cache-dir mkdocs-material mkdocs-static-i18n
COPY mkdocs.yml ./
COPY docs/site ./docs/site
RUN mkdocs build -d /built

# --- runtime ---
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["uvicorn", "agentrum.main:app", "--host", "0.0.0.0", "--port", "8080"]
