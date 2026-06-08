# Using coupang-sourcing from OpenClaw / Hermes

Give your OpenClaw (Hermes) agent a **Coupang sourcing tool**: it finds products by your
criteria, reads a product link, and accumulates everything into one SQLite sourcing DB —
via a small **MCP server** (typed tools) plus a thin **skill** (when/how to use them).

The MCP server reuses this project's collectors/storage, so the agent gets the same Tier‑1
(no browser) discovery/collection **and** Tier‑2 (search + seller resolution) that need a
brief headful Chrome to mint Akamai cookies. Run it on a host with a display + Chrome + Node
(a normal macOS desktop — the same kind of box this was built on).

## Prerequisites (on the OpenClaw host)
- This repo checked out, with a venv: `uv venv && uv pip install -e ".[mcp]"` (installs the
  `mcp` server SDK alongside the CLI).
- **Google Chrome** and **Node.js** — only for gated routes (`search`, `collect=true`,
  `product_info` from a bare link). Tier‑1 (best100, `product`/`collect_seller` with a store)
  needs neither. Override discovery with `COUPANG_CHROME` / `COUPANG_NODE` if needed.
- The Hermes agent's own env needs the **MCP client**: `pip install mcp` (per its `native-mcp`
  skill). If absent, Hermes silently disables MCP.

## Setup

1. **Install the server**
   ```bash
   cd ~/coupang-sourcing            # this repo on the OpenClaw host
   uv venv && uv pip install -e ".[mcp]"
   ```
   Sanity check it starts (Ctrl-C to stop; it speaks MCP over stdio):
   ```bash
   .venv/bin/python -m coupang_sourcing.mcp_server
   ```

2. **Register the MCP server** — merge [`integration/openclaw/config.snippet.yaml`](../integration/openclaw/config.snippet.yaml)
   into `~/.hermes/config.yaml` under the top-level `mcp_servers:` key (replace `<YOU>`/paths).

3. **Install the skill** — copy the playbook so the agent knows when/how to use the tools:
   ```bash
   mkdir -p ~/.hermes/skills/coupang-sourcing
   cp integration/openclaw/SKILL.md ~/.hermes/skills/coupang-sourcing/SKILL.md
   ```

4. **Restart the agent.** On startup it connects to the `coupang` server, discovers the tools,
   and registers them as `mcp_coupang_find_products`, `mcp_coupang_product_info`,
   `mcp_coupang_collect_seller`, `mcp_coupang_query_db`, `mcp_coupang_list_categories`,
   `mcp_coupang_refresh_cookies`.

5. **Approvals** — Hermes runs tools under its approval policy (`approvals.mode`). Approve the
   coupang tools when prompted, or add them to `command_allowlist` for unattended use. The
   first gated call opens a brief Chrome window to mint cookies (cached ~1h afterwards).

## Tools the agent gets
| Tool | Purpose |
|---|---|
| `find_products` | search (`query`) or best100 (`board`/`category`) + filters (`min_rating`/`max_price`/`min_reviews`); `collect=true` also full-collects sellers. Saves to DB. |
| `product_info` | full info for one product `url` (+ optional `store_url`). |
| `collect_seller` | a seller's catalog (`store` = shop URL or `A0…` id). |
| `query_db` | read accumulated data (`products`, `rank_snapshots`, `search_snapshots`, `reviews`, …). |
| `list_categories` | best100 categoryIds for drill-down. |
| `refresh_cookies` | force-refresh Akamai cookies. |

## Try it
After setup, ask the agent things like:
- "쿠팡에서 **의자** 중 평점 4.5↑·리뷰 1000↑ 인 거 찾아줘" → `find_products(query="의자", min_rating=4.5, min_reviews=1000)`
- "주방용품 베스트100 보여줘" → `list_categories` → `find_products(board="bestseller", category=<id>)`
- "이 링크 정보 알려줘 <coupang url>" → `product_info(url=...)`
- "이 판매자 상품 다 모아줘 <shop url>" → `collect_seller(store=...)`
- "DB에서 소싱점수 70↑ 상품" → `query_db(table="products", min_score=70)`

## Notes / limits
- The DB (default `~/.coupang-sourcing/sourcing.db`) is shared by the CLI and the MCP server —
  you can also run `coupang-sourcing export ...` against it for reports.
- best100 is ~80% Coupang-direct (no marketplace store) → seller full-collect applies to the
  marketplace minority; search has more marketplace sellers. Sellers without a public
  brandstore are skipped during collection.
- `COUPANG_MAX_REVIEW_PAGES` caps reviews per product so tool calls stay responsive (default 3;
  set `0` for all). Full-catalog collection (`collect_seller`, `collect=true`) is slower.
