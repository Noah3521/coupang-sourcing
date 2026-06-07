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

## Install

```bash
cd ~/coupang-sourcing
uv venv && uv pip install -e ".[dev]"     # or: python -m venv .venv && pip install -e ".[dev]"
```

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

### export

Dumps a table (`products`, `reviews`, `product_snapshots`, `product_variants`, `stores`,
`vendor_map`) to CSV or JSON. The `products` table can be filtered with `--store` and
`--min-score` and is sorted by sourcing score. Table names are whitelisted.

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
