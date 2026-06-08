# coupang-sourcing

A small CLI that builds a **Coupang product sourcing database**. Give it a product URL
plus its store URL and it collects everything useful for a sourcing decision — price,
discount, options, delivery/channel, the full review set, rating distribution, and derived
sourcing metrics — then upserts it into SQLite with a time-series snapshot so you can track
price and review trends over time.

## Why product URL **and** store URL?

Only the seller-store APIs (`shop.coupang.com/api/v1/*`) reliably return price/metadata, and
they require the store's `vendorId`. A bare product URL does not contain `vendorId`, and the
product-detail routes that do (`/vp/products/.../vendoritems/...`, `/np` and `/vp` pages,
`/vp/product/reviews`) are edge-protected and return **403** without a fresh `x-cp-s` cookie.
So the input contract is a **(product URL, store URL) pair**. Reviews/ratings come from the
stable `www.coupang.com/next-api/review` endpoint (productId only).

**Endpoints used (stable, non-403):**
`store/getStoreInfo`, `listing`, `store/getStoreReview`, `main_category`, `next-api/review`.
The 403-prone product-detail routes are intentionally avoided.

📖 **Full CLI reference + dependencies: [docs/CLI.md](docs/CLI.md)**
🤖 **Use it from an OpenClaw/Hermes agent (MCP server + skill): [docs/OPENCLAW.md](docs/OPENCLAW.md)**

## For an AI agent: autonomous setup (OpenClaw)

If you are an OpenClaw agent that was handed this repository URL, install yourself as a
sourcing tool with your shell/exec tool. The host has git auth, the `openclaw` CLI, Python
≥ 3.10, and (for search) Google Chrome + Node.js.

```bash
# 1. Clone (skip if already cloned) and enter the repo
git clone https://github.com/Noah3521/coupang-sourcing.git ~/coupang-sourcing 2>/dev/null || true
cd ~/coupang-sourcing && git pull --ff-only || true

# 2. Install + register (idempotent). Creates the venv, installs the [mcp] extra, verifies the
#    MCP server, then registers it with OpenClaw via:
#      openclaw mcp add coupang --command .../python --arg -m --arg coupang_sourcing.mcp_server --env ...
#      openclaw skills install integration/openclaw/skill --as coupang-sourcing --global
bash integration/openclaw/install.sh
```

Then:

3. **Reload.** Restart / reload OpenClaw if it doesn't hot-load new MCP servers
   (`openclaw mcp list` should show `coupang`; `openclaw mcp probe coupang --json` should list
   its tools).
4. **Verify.** Call the `coupang` server's `find_products` with `{"board":"trending","top":3}`;
   you should get 3 products. You're ready — the installed `coupang-sourcing` skill explains the
   rest (`find_products`, `product_info`, `collect_seller`, `query_db`, …).

Notes:
- If the `openclaw` CLI isn't on PATH, step 2 prints manual steps instead: merge
  [`integration/openclaw/mcp.config.json`](integration/openclaw/mcp.config.json) into
  `~/.openclaw/openclaw.json` (under `mcp.servers`) and copy the skill to `~/.openclaw/skills/`.
- Only `search`, `find_products(query=…)`, `collect=true`, and `product_info` from a bare link
  are Akamai-gated (need Chrome+Node; a brief headful Chrome mints cookies on first use).
  best100 discovery, `product_info` with a `store_url`, and `collect_seller` need neither.
- Every tool persists to one SQLite DB (`~/.coupang-sourcing/sourcing.db` by default).
- Full walkthrough: [docs/OPENCLAW.md](docs/OPENCLAW.md).

## Install

```bash
cd ~/coupang-sourcing
uv venv && uv pip install -e ".[dev]"     # or: python -m venv .venv && pip install -e ".[dev]"
```

> Most commands need only Python + the three pip deps (no browser, no login). `search`,
> `mint-cookies`, and `--collect` additionally need **Google Chrome + Node.js** (to mint
> Akamai cookies via a brief headful browser) — see [docs/CLI.md](docs/CLI.md).

## Usage

```bash
# create the SQLite schema
coupang-sourcing init-db --db sourcing.db

# collect one product (price + metadata + all reviews + sourcing metrics)
coupang-sourcing product \
  "https://www.coupang.com/vp/products/9042237424?itemId=26531314972&vendorItemId=93505444186" \
  "https://shop.coupang.com/A00333576" --db sourcing.db

# many at once (CSV of product,store pairs — each store's listing is scanned only once)
coupang-sourcing batch examples/batch_input.csv --db sourcing.db

# re-crawl to append price/review snapshots (trend tracking)
coupang-sourcing refresh --all --db sourcing.db
coupang-sourcing refresh --store A00333576 --older-than 7 --db sourcing.db

# collect a best100 ranking (no browser / no credentials needed)
coupang-sourcing rank --board trending --db sourcing.db          # 24시간 급상승
coupang-sourcing rank --board bestseller --db sourcing.db        # 7일 판매량 베스트
coupang-sourcing rank --board bestseller --category 177195 --top 20 --db sourcing.db
coupang-sourcing rank-categories --board bestseller              # list categoryIds to drill into

# visualize the whole DB (and collect from the UI) — Streamlit dashboard
pip install -e ".[dashboard]" && coupang-sourcing dashboard       # http://localhost:8501

# collect search results (organic vs ads); first run mints Akamai cookies via a brief Chrome window
coupang-sourcing search 의자 --db sourcing.db
coupang-sourcing search 의자 --top 20 --json --db sourcing.db
coupang-sourcing mint-cookies                                    # force-refresh the cookie cache

# discovery → full collection: resolve sellers + crawl their catalogs (rank or search)
coupang-sourcing search 의자 --collect --db sourcing.db
coupang-sourcing rank --board bestseller --category 177195 --collect --db sourcing.db

# export DB tables to CSV/JSON
coupang-sourcing export --table products --format csv --out products.csv --db sourcing.db
coupang-sourcing export --table products --min-score 70 --store A00333576 --db sourcing.db
coupang-sourcing export --table reviews --format json --out reviews.json --db sourcing.db

# schedule periodic refresh (macOS launchd; prints a cron line on other OSes)
coupang-sourcing schedule install --interval daily --at 03:00 --all --db sourcing.db
coupang-sourcing schedule install --interval daily --dry-run    # preview the plist, install nothing
coupang-sourcing schedule status
coupang-sourcing schedule uninstall
```

Add `--json` for machine-readable output, `--no-reviews` to skip review collection,
`--out DIR` (on `product`) to also dump JSON + reviews CSV.

### rank

Collects a **best100 ranking** straight from the public `/np/best100/{board}/{category}`
pages — no browser and no credentials, parsed from the server-rendered HTML with the same
chrome-impersonating client. `--board` is `trending` (24h 급상승) or `bestseller` (7일 베스트);
`--category` is `all` or a `categoryId`. Each ranking row carries `rank`, `productId`,
`itemId`, `vendorItemId`, price, rating, review count and **channel / 판매유형** (rocket /
rocket_fresh / rocket_merchant / seller), and is appended to `rank_snapshots` (a time series,
so re-running tracks rank movement). Rows whose `productId` is already in `products` are
flagged, so a ranking doubles as a **discovery feed** — tracked products vs new candidates to
feed into `product`/`batch`. The recommendation widget at the bottom of the page is dropped
(only the `toprank_unit` ranking is kept).

`rank-categories` lists the `categoryId`/name links on a board page so you can drill down
(top categories → subcategories — one `--category {id}` handles any depth).

### search (Akamai-gated — needs a browser cookie)

`search QUERY` collects a search-results page from `/np/search`, separating **organic**
(`sourceType=search`) from **ads** (`sourceType=srp_product_ads`) — each row keeps its page
position (`rank`) plus an `isAd` flag, and lands in `search_snapshots`. Unlike best100,
`/np/search` is hard-gated by Akamai, so the first gated call **mints cookies via a brief
headful Chrome window** (a real browser solves the sensor; *headless gets blocked*), then
caches them at `~/.config/coupang-sourcing/cookies.json` and replays them through the normal
chrome-impersonating client for fast bulk fetches. Cookies are re-minted automatically when
they expire or get a 403/challenge; `mint-cookies` forces a refresh. Requires Chrome (and
Node, used only to drive Chrome over CDP); override discovery with `COUPANG_CHROME` /
`COUPANG_NODE`.

### --collect (discovery → full collection)

`rank ... --collect` and `search ... --collect` resolve each result's **seller** — the cards
carry only product/item/vendorItem ids, so we read `vp/products/{pid}/vendoritems/{vid}` (a
gated JSON whose `vendor.id` is the store url-name) — then feed the marketplace ones into the
normal `(product, store)` batch flow for full price/metadata/reviews/metrics collection.
Resolution is ~once per seller (cookie, bulk-safe); the catalog crawl itself runs on the
cookie-free `listing` API. Coupang-direct (로켓 직매입) items have no marketplace store and
are skipped.

> Notes: a best100 page server-renders ~the top ~30 ranked items (the rest load via scroll/JS,
> which we don't execute). At the **category** level `trending` and `bestseller` largely
> coincide; the distinction is sharpest at `--category all`. The ranking cards expose
> product/item/vendorItem ids but **not** a per-product seller `vendorId`, so seller-level
> linkage still goes through the (product, store) flow.

### export

Dumps a table (`products`, `reviews`, `product_snapshots`, `product_variants`, `stores`,
`vendor_map`, `rank_snapshots`, `search_snapshots`) to CSV or JSON. The `products` table can
be filtered with `--store` and `--min-score` and is sorted by sourcing score. Table names are
whitelisted.

### schedule

Installs a launchd LaunchAgent (`~/Library/LaunchAgents/com.coupang-sourcing.refresh.plist`)
that runs `refresh` on an `hourly` / `daily` / `weekly` cadence, logging to
`~/Library/Logs/coupang-sourcing-refresh.log`. Use `--dry-run` to preview the plist without
installing. On non-macOS hosts it prints a `crontab -e` line instead.

## Data model (SQLite)

| table | purpose |
|---|---|
| `products` | latest snapshot per product (price, rating, channel, sourcing score) |
| `product_variants` | normalized options |
| `product_snapshots` | **time series**: price / review_total / rating per crawl |
| `reviews` | review rows for text mining |
| `stores`, `vendor_map` | store metadata + vendorName↔vendorId cache |
| `rank_snapshots` | **time series**: best100 ranking rows (board/category/rank → product) |
| `search_snapshots` | **time series**: search-result rows (query/rank, organic vs ad flag, resolved store) |

## Sourcing metrics

- **review velocity** (1/3/6/12 mo) — demand & trend
- **estimated monthly sales** — snapshot delta × `sale_multiplier` (falls back to last-month
  velocity on first crawl; it's an estimate, method is reported)
- **rating average / distribution / negative rate**
- **complaint keywords** (configurable) on negative reviews — risk signal
- **best options**, **photo-review rate**, **channel** (rocket/overseas/domestic), discount
- **sourcing score** = `w.demand·demand + w.quality·quality − w.risk·risk` (weights in config)

## Config

Copy `config.example.toml` → `config.toml` (or `~/.config/coupang-sourcing/config.toml`).
CLI flags override config values.

## Develop

```bash
uv run pytest      # unit tests (no network — uses recorded fixtures + temp DB)
uv run ruff check .
```
