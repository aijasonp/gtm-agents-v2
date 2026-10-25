#!/usr/bin/env bash
# Install the built GTM fleet into the three running NetClaw containers.
#
# Prereqs: .env filled from .env.netclaw.example, `python3 netclaw/build.py --config config` run,
# and `docker compose -f docker-compose.yml -f docker-compose.netclaw.yml up -d` started.
#
# For each instance this script:
#   1. fills ${VARS} in netclaw.json and webhook routes from .env (fails on any unset var)
#   2. writes them into the container's ~/.netclaw/config
#   3. installs the subagent files into ~/.netclaw/agents
#   4. validates and imports every reminder
#   5. restarts the container and prints MCP + skill health
set -euo pipefail
shopt -s nullglob
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "missing .env (copy .env.netclaw.example)"; exit 1; }
[ -d dist/netclaw ] || { echo "missing dist/netclaw (run python3 netclaw/build.py)"; exit 1; }
set -a; . ./.env; set +a

fill() {  # fill <file> <instance-prefix>: print file with ${VARS} substituted, fail if any are unset
  INSTANCE_PREFIX="$2" python3 - "$1" <<'PY'
import os, re, sys
text = open(sys.argv[1]).read()
prefix = os.environ["INSTANCE_PREFIX"]
def sub(m):
    name = m.group(1)
    for key in (f"{prefix}_{name}", name):          # PIPELINE_SLACK_CHANNEL_ID beats SLACK_CHANNEL_ID
        if os.environ.get(key):
            return os.environ[key]
    sys.exit(f"unset variable for {sys.argv[1]}: {prefix}_{name} or {name}")
print(re.sub(r"\$\{([A-Z0-9_]+)\}", sub, text), end="")
PY
}

for inst in pipeline deals revops; do
  c="netclaw-$inst"; P=$(echo "$inst" | tr a-z A-Z); src="dist/netclaw/$inst"
  echo "== $inst ($c)"
  docker ps --format '{{.Names}}' | grep -q "$c" || { echo "container $c is not running"; exit 1; }
  docker exec "$c" sh -c 'mkdir -p ~/.netclaw/config/webhooks ~/.netclaw/agents'

  fill "$src/config/netclaw.json" "$P" | docker exec -i "$c" sh -c 'cat > ~/.netclaw/config/netclaw.json'
  for f in "$src"/config/webhooks/*.json; do
    fill "$f" "$P" | docker exec -i "$c" sh -c "cat > ~/.netclaw/config/webhooks/$(basename "$f")"
  done
  docker exec "$c" sh -c 'cp /opt/gtm/instance/agents/*.md ~/.netclaw/agents/'

  docker restart "$c" >/dev/null && sleep 8
  for f in "$src"/reminders/*.json; do
    r="/opt/gtm/instance/reminders/$(basename "$f")"
    docker exec "$c" netclaw reminder validate "$r" && docker exec "$c" netclaw reminder import "$r"
  done

  echo "-- MCP servers"; docker exec "$c" netclaw mcp list || true
  echo "-- skill issues"; docker exec "$c" netclaw skill issues || true
done
echo "Done. Next: run 'docker exec -it netclaw-<instance> netclaw mcp permissions' to set read-only CRM and workspace tools to Auto."
