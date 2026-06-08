---
name: coupang-sourcing
description: "Coupang sourcing: find products by criteria, look up a link, build a sourcing DB."
version: 1.0.0
metadata:
  hermes:
    tags: [coupang, sourcing, ecommerce, products, korea, 쿠팡, 소싱, 상품, 판매자]
    related_skills: [native-mcp]
---

# Coupang Sourcing

Build and query a Coupang product **sourcing database**. The `coupang` MCP server exposes
typed tools (no manual CLI needed); every call also **accumulates data into one SQLite DB**,
so sourcing knowledge grows over time.

## When to Use
- User wants to **find products by criteria** ("의자 중에 평점 4.5 이상 리뷰 많은 거 찾아줘", "주방용품 베스트 보여줘").
- User **sends a Coupang product link** and wants its info / sourcing read.
- User wants a **seller's whole catalog** collected.
- User asks about **already-collected data** ("DB에 쌓인 것 중 소싱점수 높은 거", "이 스토어 상품들").

## Available Tools
| Tool | When to use |
|------|------------|
| `mcp_coupang_find_products` | Find products. `query` → search (organic + ads). No `query` → best100 ranking (`board`=trending\|bestseller, `category`). Filters: `min_rating`, `max_price`, `min_reviews`. `collect=true` also full-collects marketplace sellers. Always saves to DB. |
| `mcp_coupang_product_info` | Full info for one product `url` (price, discount, rating, channel, review/sourcing metrics). Pass `store_url` if known; else seller is auto-resolved. |
| `mcp_coupang_collect_seller` | Collect a seller's catalog (`store` = shop URL or id like `A00333576`, `limit` products). |
| `mcp_coupang_query_db` | Read accumulated data: `table` = products \| rank_snapshots \| search_snapshots \| reviews \| stores. `products` supports `min_score`/`store`. |
| `mcp_coupang_list_categories` | List best100 categoryIds to drill into `find_products`. |
| `mcp_coupang_refresh_cookies` | Force-refresh Akamai cookies (only if a gated call keeps failing). |

## Workflows

**"~ 조건으로 찾아줘"** — pick the source, then filter:
- A keyword? → `find_products(query="의자", min_rating=4.5, min_reviews=500, top=30)`.
- A category bestseller? → `find_products(board="bestseller", category="<id>")` (use `list_categories` first if the id is unknown).
- Then show a short ranked table (rank · title · price · rating(reviews) · link), and note results were saved to the DB. Offer `collect=true` (or `product_info`) if they want full data.

**Product link → info** — `product_info(url="<coupang link>")`. Show price/discount, rating + review count, channel, sourcing score, est. monthly sales. Saved to DB.

**Seller catalog** — `collect_seller(store="<shop url or A0...>")`.

**Query accumulated data** — `query_db(table="products", min_score=70)` for the best sourcing candidates; `query_db(table="search_snapshots")` / `rank_snapshots` for discovery history.

## Rules
- **best100 (no `query`) needs no browser and is fast/bulk-safe** — prefer it for broad discovery.
- **search (`query`) and `collect=true` are gated**: the first such call may briefly open a Chrome window to mint cookies (then cached ~1h). This is normal — don't tell the user it failed; if a tool returns an `error` about cookies/Akamai, call `refresh_cookies` once and retry.
- `collect=true` and `collect_seller` are **slower** (they crawl full catalogs + reviews) — use only when the user wants depth, and say it may take a bit.
- **best100 is ~80% Coupang-direct** (no marketplace seller) → seller resolution / full-collect applies to the minority that are marketplace sellers. Search results have more marketplace sellers.
- Results are **already persisted**; don't claim you "can't save". Be concise — show the top items, not raw JSON dumps.
- If a tool returns `{"error": ...}`, relay it plainly and suggest the fix it implies (e.g. provide `store_url`).
