# Using coupang-sourcing from OpenClaw

Give your OpenClaw agent a **Coupang sourcing tool**: it finds products by your criteria,
reads a product link, collects sellers, and accumulates everything into one SQLite DB — via a
small **MCP server** (typed tools) registered in OpenClaw, plus a thin **skill** (when/how to
use them).

The MCP server reuses this project's collectors/storage, so the agent gets Tier‑1 (no browser)
discovery/collection **and** Tier‑2 (search + seller resolution) that need a brief headful
Chrome to mint Akamai cookies. Run it on a host with a display + Chrome + Node (a normal macOS
desktop).

## Prerequisites (on the OpenClaw host)
- This repo checked out, with a venv: `uv venv && uv pip install -e ".[mcp]"` (installs the
  `mcp` server SDK used by our server alongside the CLI).
- **OpenClaw** installed (the `openclaw` CLI on PATH). Config lives at `~/.openclaw/openclaw.json`.
- **Google Chrome** + **Node.js** — only for gated routes (`search`, `collect=true`,
  `product_info` from a bare link). Tier‑1 needs neither. Override with `COUPANG_CHROME` /
  `COUPANG_NODE` if not auto-detected.

## Setup (one command)
```bash
cd ~/coupang-sourcing            # this repo on the OpenClaw host
bash integration/openclaw/install.sh
```
The installer: creates the venv + installs `.[mcp]`, verifies the MCP server, then — if the
`openclaw` CLI is present — registers everything:
```bash
openclaw mcp add coupang --command <repo>/.venv/bin/python \
  --arg -m --arg coupang_sourcing.mcp_server \
  --env COUPANG_SOURCING_DB=~/.coupang-sourcing/sourcing.db \
  --env COUPANG_MAX_REVIEW_PAGES=3 [--env COUPANG_CHROME=… --env COUPANG_NODE=…]
openclaw skills install <repo>/integration/openclaw/skill --as coupang-sourcing --global
openclaw mcp probe coupang --json     # sanity check
```
If the `openclaw` CLI isn't on PATH, the installer prints the manual steps instead (merge
[`integration/openclaw/mcp.config.json`](../integration/openclaw/mcp.config.json) into
`~/.openclaw/openclaw.json` under `mcp.servers`, and copy the skill to `~/.openclaw/skills/`).

Reload/restart OpenClaw if it doesn't hot-load MCP servers.

## Tools the agent gets (from the `coupang` server)
| Tool | Purpose |
|---|---|
| `find_products` | search (`query`) or best100 (`board`/`category`) + filters; `collect=true` full-collects sellers. Saves to DB. |
| `product_info` | full info for one product `url` (+ optional `store_url`). |
| `collect_seller` | a seller's catalog (`store` = shop URL or `A0…` id). |
| `query_db` | read accumulated data (`products`, `rank_snapshots`, `search_snapshots`, `reviews`, …). |
| `list_categories` | best100 categoryIds for drill-down. |
| `refresh_cookies` | force-refresh Akamai cookies. |

## Try it
- "쿠팡에서 **의자** 중 평점 4.5↑·리뷰 1000↑ 찾아줘" → `find_products(query="의자", min_rating=4.5, min_reviews=1000)`
- "주방용품 베스트100 보여줘" → `list_categories` → `find_products(board="bestseller", category=<id>)`
- "이 링크 정보 알려줘 <coupang url>" → `product_info(url=...)`
- "이 판매자 상품 다 모아줘 <shop url>" → `collect_seller(store=...)`
- "DB에서 소싱점수 70↑ 상품" → `query_db(table="products", min_score=70)`

## Notes / limits
- The DB (default `~/.coupang-sourcing/sourcing.db`) is shared by the CLI and MCP server — you
  can also run `coupang-sourcing export …` against it for reports.
- best100 is ~80% Coupang-direct (no marketplace store) → seller full-collect applies to the
  marketplace minority; search has more. Sellers without a public brandstore are skipped.
- `COUPANG_MAX_REVIEW_PAGES` caps reviews per product so tool calls stay responsive (default 3;
  `0` = all). Full-catalog collection (`collect_seller`, `collect=true`) is slower.
- Approve the `coupang` tools under OpenClaw's tool policy (or allowlist them) for unattended
  use. The first gated call briefly opens Chrome to mint cookies (cached ~1h).
