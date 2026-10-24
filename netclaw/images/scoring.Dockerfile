# Scoring engine MCP server (JEV/CLEF). Build from the repo root:
#   docker build -f netclaw/images/scoring.Dockerfile -t gtm-scoring .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "requests>=2.31" "pyyaml>=6" "mcp>=1.2"
WORKDIR /app
COPY library/outbound-engine/typesafe_client.py library/outbound-engine/scoring_mcp.py library/outbound-engine/product_profile.example.yaml ./
RUN useradd -m gtm && mkdir -p /data/account-knowledge && chown -R gtm /data
USER gtm
ENV GTM_ACCOUNT_KNOWLEDGE_DIR=/data/account-knowledge
ENTRYPOINT ["python3", "/app/scoring_mcp.py", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8010"]
