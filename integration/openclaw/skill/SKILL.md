---
name: coupang-sourcing
description: "Coupang sourcing — find products by criteria, look up a link, build a sourcing DB. Uses the `coupang` MCP server."
metadata: { "openclaw": { "emoji": "🛒" } }
---

# Coupang Sourcing

Build and query a Coupang product **sourcing database**. The `coupang` MCP server provides
typed tools; every call also **accumulates data into one SQLite DB**, so sourcing knowledge
grows over time.

## When to Use
- Find products by **criteria** ("의자 중 평점 4.5↑ 리뷰 많은 거 찾아줘", "주방용품 베스트 보여줘").
- A user **sends a Coupang product link** and wants its info / sourcing read.
- Collect a **seller's whole catalog**.
- Query **already-collected data** ("DB에서 소싱점수 높은 거", "이 스토어 상품들").

## Tools (from the `coupang` MCP server)
| Tool | When to use |
|------|------------|
| `find_products` | Find products. `query` → search (organic + ads, each `isAd`). No `query` → best100 (`board`=trending\|bestseller, `category`). Filters `min_rating`/`max_price`/`min_reviews`. `collect=true` also full-collects marketplace sellers. Saves to DB. |
| `product_info` | Full info for one product `url` (price/discount/rating/channel/sourcing metrics). Pass `store_url` if known; else seller auto-resolved. |
| `collect_seller` | Collect a seller's catalog (`store` = shop URL or id like `A00333576`, `limit`). |
| `query_db` | Read accumulated data: `table` = products \| rank_snapshots \| search_snapshots \| reviews \| stores. `products` supports `min_score`/`store`. |
| `list_categories` | List best100 categoryIds to drill into `find_products`. |
| `refresh_cookies` | Force-refresh Akamai cookies (only if a gated call keeps failing). |
| `source_1688` | Find the **1688 origin/원가** of Coupang product(s) by image search. `product_id` → one product (else all un-sourced). Stores top-N 1688 offers + full metadata as children. `top`/`headless_top`/`limit`/`resource`. Slow (headless renders). |
| `query_1688` | Read stored 1688 origins: `product_id` → that product's ranked 1688 offers (price¥/sales/seller); none → products sourced + cheapest 1688 price. |

## Workflows
**"~ 조건으로 찾아줘"** — pick the source, then filter:
- keyword → `find_products(query="의자", min_rating=4.5, min_reviews=500, top=30)`
- category bestseller → `find_products(board="bestseller", category="<id>")` (use `list_categories` if id unknown)
- Show a short ranked table (rank · title · price · rating(reviews) · link); note it's saved to DB. Offer `collect=true` / `product_info` for full data.

**Product link → info** — `product_info(url="<link>")`. Show price/discount, rating + reviews, channel, sourcing score, est. monthly sales.

**Seller catalog** — `collect_seller(store="<shop url or A0...>")`.

**Query accumulated data** — `query_db(table="products", min_score=70)` for best candidates.

**"이 쿠팡 상품 1688 원가 찾아줘" / 소싱 마진** — `source_1688(product_id="<id>")` (없으면 미소싱 전체), 그다음 `query_1688(product_id="<id>")`로 1688 후보(가격¥·판매·판매자) 표시. 쿠팡 판매가 vs 1688 원가로 마진 코멘트. 헤드리스 렌더라 **느리다** — 한 상품씩 또는 `limit`로 좁히고 "시간이 걸린다"고 안내. (별도 1회 셋업 필요: `integration/aliprice-1688` → `bash install.sh` + `node decrypt-cookies.js`.)

## Rules
- **best100 (no `query`) needs no browser and is fast/bulk-safe** — prefer it for broad discovery.
- **search (`query`) and `collect=true` are gated**: the first such call may briefly open a Chrome window to mint cookies (cached ~1h). This is normal — if a tool returns an `error` about cookies/Akamai, call `refresh_cookies` once and retry. Never tell the user you "can't".
- `collect=true` and `collect_seller` are **slower** (full catalogs + reviews) — use only when depth is wanted, and say it may take a bit.
- **best100 is ~80% Coupang-direct** (no marketplace seller) → full-collect applies to the marketplace minority; search has more marketplace sellers.
- Results are **already persisted** — be concise, show top items, not raw JSON dumps. If a tool returns `{"error": ...}`, relay it and apply the implied fix (e.g. provide `store_url`).
