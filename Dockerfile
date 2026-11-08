# Exec Brief card renderer (json-render + Chat SDK). Optional: without Node the agent renders Block Kit in Python.
FROM node:22-slim AS exec-brief-render
WORKDIR /render
COPY agents/exec-brief/delivery/package.json agents/exec-brief/delivery/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GTM_AGENTS_DIR=/app/agents GTM_DATA_DIR=/app/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY core ./core
RUN pip install --no-cache-dir ".[mcp,postgres,slack,aws,warehouse]"
COPY config ./config
COPY agents ./agents
COPY --from=exec-brief-render /usr/local/bin/node /usr/local/bin/node
COPY --from=exec-brief-render /render/node_modules ./agents/exec-brief/delivery/node_modules
COPY evals ./evals
RUN useradd -m gtm && mkdir -p /app/data && chown -R gtm /app/data
USER gtm
# Release gate inside the image: the build fails if any agent's evals fail.
RUN python -m evals.runner
ENTRYPOINT ["gtm"]
CMD ["schedule"]
