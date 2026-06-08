#!/usr/bin/env bash
# coupang-sourcing :: OpenClaw installer (deterministic + idempotent).
# Run from anywhere inside the cloned repo:  bash integration/openclaw/install.sh
# Does: venv + `pip install -e .[mcp]`, verify the MCP server, then register it with OpenClaw
# (via the `openclaw` CLI if present, else print manual JSON/skill steps).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO"
DB="${COUPANG_SOURCING_DB:-$HOME/.coupang-sourcing/sourcing.db}"
echo "==> repo: $REPO"

# --- 1) venv + install with the mcp extra ---
if command -v uv >/dev/null 2>&1; then
  uv venv >/dev/null 2>&1 || true
  uv pip install -e ".[mcp]" >/dev/null
else
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/python -m pip install -q --upgrade pip
  ./.venv/bin/python -m pip install -q -e ".[mcp]"
fi
PYBIN="$REPO/.venv/bin/python"
mkdir -p "$(dirname "$DB")"
echo "==> python: $PYBIN"

# --- 2) detect Chrome / Node (only needed for gated routes: search, --collect) ---
CHROME="$( [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] && echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" || command -v google-chrome 2>/dev/null || true )"
NODE="$( command -v node 2>/dev/null || ls "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | tail -1 || true )"
[ -n "$CHROME" ] && echo "==> chrome: $CHROME" || echo "==> chrome: NOT FOUND (gated search/--collect unavailable)"
[ -n "$NODE" ]   && echo "==> node:   $NODE"   || echo "==> node:   NOT FOUND (gated search/--collect unavailable)"

# --- 3) verify the MCP server loads + registers tools ---
echo "==> verifying MCP server…"
COUPANG_SOURCING_DB="$DB" "$PYBIN" -c "import asyncio; from coupang_sourcing import mcp_server as S; print('    tools:', [t.name for t in asyncio.run(S.mcp.list_tools())])"

# --- 4) register with OpenClaw ---
if command -v openclaw >/dev/null 2>&1; then
  echo "==> registering via the openclaw CLI"
  openclaw mcp unset coupang >/dev/null 2>&1 || true   # idempotent re-add
  ENVARGS=(--env "COUPANG_SOURCING_DB=$DB" --env "COUPANG_MAX_REVIEW_PAGES=3")
  [ -n "$CHROME" ] && ENVARGS+=(--env "COUPANG_CHROME=$CHROME")
  [ -n "$NODE" ]   && ENVARGS+=(--env "COUPANG_NODE=$NODE")
  openclaw mcp add coupang --command "$PYBIN" --arg -m --arg coupang_sourcing.mcp_server "${ENVARGS[@]}"
  openclaw skills install "$REPO/integration/openclaw/skill" --as coupang-sourcing --global \
    || echo "    (skill may already be installed — ok)"
  echo "==> probe:"
  openclaw mcp probe coupang --json || true
  echo
  echo "DONE. Reload/restart OpenClaw if needed. Tools: find_products, product_info,"
  echo "collect_seller, query_db, list_categories, refresh_cookies."
else
  cat <<EOF

==> 'openclaw' CLI not on PATH — register manually:

1) Merge into ~/.openclaw/openclaw.json under "mcp": { "servers": { ... } }:

   "coupang": {
     "command": "$PYBIN",
     "args": ["-m", "coupang_sourcing.mcp_server"],
     "env": { "COUPANG_SOURCING_DB": "$DB", "COUPANG_MAX_REVIEW_PAGES": "3"$( [ -n "$CHROME" ] && printf ',\n              "COUPANG_CHROME": "%s"' "$CHROME" )$( [ -n "$NODE" ] && printf ',\n              "COUPANG_NODE": "%s"' "$NODE" ) },
     "timeout": 300,
     "connectTimeout": 60
   }

2) Install the skill:
   mkdir -p ~/.openclaw/skills/coupang-sourcing
   cp "$REPO/integration/openclaw/skill/SKILL.md" ~/.openclaw/skills/coupang-sourcing/SKILL.md

3) Restart OpenClaw. Tools appear from the 'coupang' server.
EOF
fi
