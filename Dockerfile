FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GTM_AGENTS_DIR=/app/agents GTM_DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml ./
COPY core ./core
RUN pip install --no-cache-dir ".[mcp,postgres]"
COPY agents ./agents
COPY evals ./evals
RUN useradd -m gtm && mkdir -p /data && chown gtm /data
USER gtm
# Release gate inside the image: the build fails if any agent's evals fail.
RUN python -m evals.runner
ENTRYPOINT ["gtm"]
CMD ["schedule"]
