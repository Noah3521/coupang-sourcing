#!/usr/bin/env bash
# coupang-sourcing :: OpenClaw/Hermes installer.
# Deterministic + idempotent. Run from anywhere inside the cloned repo:
#     bash integration/openclaw/install.sh
# Does: venv + `pip install -e .[mcp]`, install the skill, verify the MCP server,
# then print a ready-to-merge `mcp_servers:` block with resolved absolute paths.
set -euo pipefail

# --- locate repo root (this script lives in integration/openclaw/) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO"
HERMES="${HERMES_HOME:-$HOME/.hermes}"
DB="${COUPANG_SOURCING_DB:-$HOME/.coupang-sourcing/sourcing.db}"
echo "==> repo:   $REPO"
echo "==> hermes: $HERMES"

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
echo "==> installed into $PYBIN"

# --- 2) install the skill ---
SKILL_DST="$HERMES/skills/coupang-sourcing"
mkdir -p "$SKILL_DST"
cp "$REPO/integration/openclaw/SKILL.md" "$SKILL_DST/SKILL.md"
echo "==> skill -> $SKILL_DST/SKILL.md"

# --- 3) detect Chrome / Node (only needed for gated routes: search, --collect) ---
CHROME="$( [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] && echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" || command -v google-chrome 2>/dev/null || true )"
NODE="$( command -v node 2>/dev/null || ls "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | tail -1 || true )"
[ -n "$CHROME" ] && echo "==> chrome: $CHROME" || echo "==> chrome: NOT FOUND (gated search/--collect will be unavailable)"
[ -n "$NODE" ]   && echo "==> node:   $NODE"   || echo "==> node:   NOT FOUND (gated search/--collect will be unavailable)"

# --- 4) verify the MCP server loads + registers tools ---
echo "==> verifying MCP server…"
COUPANG_SOURCING_DB="$DB" "$PYBIN" -c "import asyncio; from coupang_sourcing import mcp_server as S; print('    tools:', [t.name for t in asyncio.run(S.mcp.list_tools())])"

# --- 5) print the ready-to-merge config block ---
mkdir -p "$(dirname "$DB")"
cat <<EOF

============================================================================
ADD THIS to $HERMES/config.yaml under a top-level 'mcp_servers:' key.
(Back up the file first; if 'mcp_servers:' already exists, add 'coupang:' under it;
 skip if a 'coupang:' entry is already present.)
----------------------------------------------------------------------------
mcp_servers:
  coupang:
    command: "$PYBIN"
    args: ["-m", "coupang_sourcing.mcp_server"]
    env:
      COUPANG_SOURCING_DB: "$DB"
      COUPANG_MAX_REVIEW_PAGES: "3"$( [ -n "$CHROME" ] && printf '\n      COUPANG_CHROME: "%s"' "$CHROME" )$( [ -n "$NODE" ] && printf '\n      COUPANG_NODE: "%s"' "$NODE" )
    timeout: 300
    connect_timeout: 60
----------------------------------------------------------------------------
Then: ensure the agent's own env has the MCP client ('pip install mcp'),
restart the agent, and the tools appear as mcp_coupang_*.
============================================================================
EOF
