#!/usr/bin/env sh
# Serve every runtime agent's tools over MCP (streamable HTTP) in one container.
# Ports come from netclaw/fleet.yaml. Used by the gtm-tools service in
# docker-compose.netclaw.yml; NetClaw instances reach them at http://gtm-tools:<port>/mcp.
set -eu
FLEET="${FLEET:-/app/netclaw/fleet.yaml}"
python3 - "$FLEET" <<'PY' > /tmp/mcp-ports
import sys, yaml
for name, s in yaml.safe_load(open(sys.argv[1]))["mcp_servers"].items():
    print(name, s["port"])
PY
pids=""
while read -r agent port; do
  gtm serve-mcp "$agent" --transport streamable-http --host 0.0.0.0 --port "$port" &
  pids="$pids $!"
  echo "serving $agent on :$port"
done < /tmp/mcp-ports
# Exit (and let Docker restart us) if any server dies.
while :; do
  for p in $pids; do kill -0 "$p" 2>/dev/null || { echo "server $p exited"; exit 1; }; done
  sleep 10
done
