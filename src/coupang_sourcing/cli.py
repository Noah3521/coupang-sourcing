"""coupang-sourcing CLI (Typer + Rich)."""
from __future__ import annotations

import json as jsonlib
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import exporters, scheduler, storage
from .collectors import batch as batch_mod
from .collectors import product as product_mod
from .collectors import ranking as ranking_mod
from .collectors import search as search_mod
from .collectors import seller as seller_mod
from .collectors import store as store_mod
from .config import Config
from .http_client import CoupangClient
from .models import ProductRecord
from .urls import parse_product, parse_store

app = typer.Typer(add_completion=False, help="Coupang product sourcing collector.")
schedule_app = typer.Typer(help="Manage a periodic `refresh` schedule (macOS launchd).")
app.add_typer(schedule_app, name="schedule")
out_console = Console()
err_console = Console(stderr=True)


def _build_config(
    db: Path | None, config_path: Path | None, rate: float | None,
    timeout: float | None, retries: int | None, review_size: int | None,
) -> Config:
    cfg = Config.load(config_path)
    return cfg.override(
        db_path=db, rate_delay=rate, timeout=timeout, retries=retries, review_size=review_size,
    )


def _progress_fn(quiet: bool):
    if quiet:
        return None
    return lambda message: err_console.print(f"[dim]· {message}[/dim]")


def _full_collect_resolved(client: CoupangClient, cfg: Config, items: list[dict], progress) -> int:
    """Resolve each ranked/searched row to its seller, then full-collect marketplace ones.

    Annotates items in place with `store`; reuses the existing (product, store) batch flow,
    so resolution (cookie, ~once per seller) feeds the cookie-free, bulk-safe listing crawl.
    """
    seller_mod.resolve_sellers(client, items, progress=progress)
    pairs = [(str(it["productId"]), it["store"]) for it in items if it.get("store")]
    if not pairs:
        return 0
    storage.init_db(cfg.db_path)
    records = batch_mod.collect_batch(
        client, pairs, cfg, progress=progress,
        on_record=lambda rec: storage.save_record(cfg.db_path, rec),
    )
    return len(records)


def _print_record_table(record: ProductRecord) -> None:
    m = record.metrics
    vel = m.get("reviewVelocity") or {}
    table = Table(title=f"{record.product.get('title')}", show_header=False, title_justify="left")
    table.add_column("field", style="cyan")
    table.add_column("value")
    table.add_row("productId", record.product_id)
    table.add_row("store", f"{record.store.get('storeName')} ({record.store.get('vendorId')})")
    table.add_row("price", f"{record.product.get('price'):,}원" if record.product.get("price") else "-")
    orig = record.product.get("originalPrice")
    disc = record.product.get("discountRate")
    table.add_row("original / discount", f"{orig:,}원 / {disc}%" if orig else "-")
    table.add_row("channel", str(m.get("channel")))
    table.add_row("rating", f"{m.get('ratingAverage')} ({m.get('ratingCount')} reviews)")
    table.add_row("reviews collected", str(len(record.reviews.get("reviews", []))))
    table.add_row("velocity 1/3/6mo", f"{vel.get('last1mo')}/{vel.get('last3mo')}/{vel.get('last6mo')}")
    table.add_row("negative rate", str(m.get("negativeRate")))
    est = m.get("estimatedSales") or {}
    table.add_row("est. sales/mo", f"{est.get('estimatedSalesPerMonth')} ({est.get('method')})")
    table.add_row("sourcing score", str(m.get("sourcingScore")))
    out_console.print(table)


def _record_summary(record: ProductRecord, files: dict | None = None) -> dict:
    m = record.metrics
    summary = {
        "productId": record.product_id,
        "title": record.product.get("title"),
        "store": record.store.get("storeName"),
        "price": record.product.get("price"),
        "originalPrice": record.product.get("originalPrice"),
        "discountRate": record.product.get("discountRate"),
        "channel": m.get("channel"),
        "ratingAverage": m.get("ratingAverage"),
        "reviewTotal": m.get("ratingCount"),
        "reviewsCollected": len(record.reviews.get("reviews", [])),
        "sourcingScore": m.get("sourcingScore"),
        "estimatedSales": m.get("estimatedSales"),
        "elapsedSeconds": record.elapsed_seconds,
    }
    if files:
        summary["files"] = files
    return summary


@app.command("init-db")
def init_db_cmd(db: Path = typer.Option(Path("coupang_sourcing.db"), "--db", help="SQLite DB path.")):
    """Create the SQLite schema."""
    storage.init_db(db)
    out_console.print(f"[green]initialized[/green] {db.resolve()}")


@app.command()
def product(
    product_url: str = typer.Argument(..., help="Product detail URL or productId."),
    store_url: str = typer.Argument(..., help="Store URL (shop.coupang.com/...) or store id."),
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    config_path: Path | None = typer.Option(None, "--config"),
    out: Path | None = typer.Option(None, "--out", help="Also write JSON/CSV files to this dir."),
    rate: float | None = typer.Option(None, "--rate", help="Base delay between requests (s)."),
    timeout: float | None = typer.Option(None, "--timeout"),
    retries: int | None = typer.Option(None, "--retries"),
    review_size: int | None = typer.Option(None, "--review-size"),
    fetch_reviews: bool = typer.Option(True, "--reviews/--no-reviews"),
    save_db: bool = typer.Option(True, "--db-save/--no-db-save", help="Upsert into the SQLite DB."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON only."),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """Collect ALL info for one product (price + metadata + reviews + sourcing metrics)."""
    cfg = _build_config(db, config_path, rate, timeout, retries, review_size)
    progress = _progress_fn(quiet or as_json)
    client = CoupangClient(cfg)
    store = parse_store(store_url)
    ids = parse_product(product_url)

    store_info = store_mod.resolve_store(client, store)
    prior = None
    if save_db:
        storage.init_db(cfg.db_path)
        conn = storage.connect(cfg.db_path)
        prior = storage.get_prior_snapshot(conn, str(ids["productId"]))
        conn.close()

    try:
        record = product_mod.collect_product(
            client, ids, store_info, cfg,
            fetch_reviews=fetch_reviews, prior_snapshot=prior, progress=progress,
        )
    except LookupError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if save_db:
        storage.save_record(cfg.db_path, record)
    files = None
    if out:
        from .exporters import export_product
        files = export_product(out, record)

    if as_json:
        out_console.print_json(jsonlib.dumps(_record_summary(record, files), ensure_ascii=False))
    else:
        _print_record_table(record)
        if save_db:
            out_console.print(f"[green]saved to DB[/green] {cfg.db_path.resolve()}")
        if files:
            out_console.print(f"[green]files[/green] {files['record']}")


@app.command()
def batch(
    input_csv: Path = typer.Argument(..., help="CSV of product,store pairs."),
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    config_path: Path | None = typer.Option(None, "--config"),
    rate: float | None = typer.Option(None, "--rate"),
    timeout: float | None = typer.Option(None, "--timeout"),
    retries: int | None = typer.Option(None, "--retries"),
    review_size: int | None = typer.Option(None, "--review-size"),
    fetch_reviews: bool = typer.Option(True, "--reviews/--no-reviews"),
    as_json: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """Collect many products from a CSV (scans each store's listing only once)."""
    cfg = _build_config(db, config_path, rate, timeout, retries, review_size)
    progress = _progress_fn(quiet or as_json)
    pairs = batch_mod.read_pairs(input_csv)
    if not pairs:
        err_console.print("[red]no (product,store) pairs found in CSV[/red]")
        raise typer.Exit(1)
    storage.init_db(cfg.db_path)
    client = CoupangClient(cfg)

    def on_record(rec: ProductRecord) -> None:
        storage.save_record(cfg.db_path, rec)

    records = batch_mod.collect_batch(
        client, pairs, cfg, fetch_reviews=fetch_reviews, progress=progress, on_record=on_record,
    )
    summaries = [_record_summary(r) for r in records]
    if as_json:
        out_console.print_json(jsonlib.dumps(summaries, ensure_ascii=False))
    else:
        table = Table(title=f"batch: {len(records)}/{len(pairs)} collected")
        for col in ("productId", "title", "price", "rating", "reviews", "score"):
            table.add_column(col)
        for s in summaries:
            table.add_row(
                str(s["productId"]), (s["title"] or "")[:40], f"{s['price']:,}" if s["price"] else "-",
                str(s["ratingAverage"]), str(s["reviewsCollected"]), str(s["sourcingScore"]),
            )
        out_console.print(table)
        out_console.print(f"[green]saved to DB[/green] {cfg.db_path.resolve()}")


@app.command()
def rank(
    board: str = typer.Option("bestseller", "--board",
                              help="trending (24h 급상승) | bestseller (7일 베스트)."),
    category: str = typer.Option("all", "--category",
                                 help="'all' or a categoryId (see rank-categories)."),
    top: int = typer.Option(0, "--top", help="Limit to the first N ranked items (0 = all on page 1)."),
    collect: bool = typer.Option(False, "--collect",
                                 help="Resolve sellers (browser cookie) + full-collect marketplace items."),
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    config_path: Path | None = typer.Option(None, "--config"),
    rate: float | None = typer.Option(None, "--rate"),
    timeout: float | None = typer.Option(None, "--timeout"),
    retries: int | None = typer.Option(None, "--retries"),
    save_db: bool = typer.Option(True, "--db-save/--no-db-save", help="Append to rank_snapshots."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON only."),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """Collect a best100 ranking (trending/bestseller, optionally by category).

    No browser/credentials needed (best100 is open). Ranked rows already in the DB are
    flagged so the ranking doubles as a discovery feed. With --collect, marketplace sellers
    are resolved (browser-minted cookie) and their products fully collected.
    """
    if board not in ranking_mod.BOARDS:
        err_console.print(f"[red]--board must be one of {ranking_mod.BOARDS}[/red]")
        raise typer.Exit(1)
    cfg = _build_config(db, config_path, rate, timeout, retries, None)
    progress = _progress_fn(quiet or as_json)
    client = CoupangClient(cfg)
    try:
        result = ranking_mod.collect_ranking(client, board, category, top=top, progress=progress)
    except (ValueError, RuntimeError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    items = result["items"]

    known_ids: set[str] = set()
    if cfg.db_path.exists():
        conn = storage.connect(cfg.db_path)
        known_ids = storage.existing_product_ids(conn)
        conn.close()
    for it in items:
        it["inDb"] = str(it["productId"]) in known_ids

    collected = 0
    if collect:
        try:
            collected = _full_collect_resolved(client, cfg, items, progress)
        except RuntimeError as exc:
            err_console.print(f"[red]collect error:[/red] {exc}")

    captured_at = None
    if save_db:
        storage.init_db(cfg.db_path)
        captured_at = storage.save_ranking(cfg.db_path, board, str(category), items)

    known = sum(1 for it in items if it["inDb"])
    new = len(items) - known
    if as_json:
        out_console.print_json(jsonlib.dumps({
            "board": board, "category": str(category), "url": result["url"],
            "capturedAt": captured_at or result["capturedAt"],
            "count": len(items), "inDb": known, "new": new, "collected": collected, "items": items,
        }, ensure_ascii=False))
        return

    table = Table(title=f"{board} / {category}  ({len(items)} ranked)")
    for col in ("#", "productId", "title", "price", "rating", "channel", "DB"):
        table.add_column(col)
    for it in items:
        table.add_row(
            str(it["rank"]), str(it["productId"]), (it["title"] or "")[:38],
            f"{it['price']:,}" if it["price"] else "-",
            f"{it['ratingAverage']} ({it['reviewCount']})" if it["ratingAverage"] else "-",
            it["channel"], "✓" if it["inDb"] else "",
        )
    out_console.print(table)
    out_console.print(f"[green]{len(items)} ranked[/green] · DB에 있음 {known} · 신규 후보 {new}")
    if collect:
        out_console.print(f"[green]full-collected[/green] {collected} marketplace products")
    if save_db:
        out_console.print(f"[green]saved to DB[/green] {cfg.db_path.resolve()}")


@app.command("rank-categories")
def rank_categories(
    board: str = typer.Option("bestseller", "--board", help="trending | bestseller."),
    category: str = typer.Option("all", "--category", help="Parent categoryId to list children of."),
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    config_path: Path | None = typer.Option(None, "--config"),
    rate: float | None = typer.Option(None, "--rate"),
    timeout: float | None = typer.Option(None, "--timeout"),
    retries: int | None = typer.Option(None, "--retries"),
    as_json: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """List the best100 categories available on a board/category page (for drill-down)."""
    if board not in ranking_mod.BOARDS:
        err_console.print(f"[red]--board must be one of {ranking_mod.BOARDS}[/red]")
        raise typer.Exit(1)
    cfg = _build_config(db, config_path, rate, timeout, retries, None)
    progress = _progress_fn(quiet or as_json)
    client = CoupangClient(cfg)
    try:
        cats = ranking_mod.collect_categories(client, board, category, progress)
    except (ValueError, RuntimeError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    if as_json:
        out_console.print_json(jsonlib.dumps(cats, ensure_ascii=False))
        return
    table = Table(title=f"best100 categories ({board}/{category})")
    table.add_column("categoryId")
    table.add_column("name")
    for c in cats:
        table.add_row(c["categoryId"], c["name"])
    out_console.print(table)
    out_console.print(f"[dim]drill down: coupang-sourcing rank --board {board} --category <id>[/dim]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search keyword (e.g. 의자)."),
    page: int = typer.Option(1, "--page", help="Result page (1 = first page)."),
    top: int = typer.Option(0, "--top", help="Limit to the first N results (0 = all on page)."),
    collect: bool = typer.Option(False, "--collect",
                                 help="Resolve sellers + full-collect marketplace results."),
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    config_path: Path | None = typer.Option(None, "--config"),
    rate: float | None = typer.Option(None, "--rate"),
    timeout: float | None = typer.Option(None, "--timeout"),
    retries: int | None = typer.Option(None, "--retries"),
    save_db: bool = typer.Option(True, "--db-save/--no-db-save", help="Append to search_snapshots."),
    as_json: bool = typer.Option(False, "--json"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """Collect a search-results ranking (organic vs ads separated).

    Search is Akamai-gated, so the first call mints Akamai cookies via a brief headful
    Chrome window (then cached/reused). Ads (`sourceType=srp_product_ads`) are flagged
    separately from organic results.
    """
    cfg = _build_config(db, config_path, rate, timeout, retries, None)
    progress = _progress_fn(quiet or as_json)
    client = CoupangClient(cfg)
    try:
        result = search_mod.collect_search(client, query, page=page, top=top, progress=progress)
    except (ValueError, RuntimeError) as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    items = result["items"]

    known_ids: set[str] = set()
    if cfg.db_path.exists():
        conn = storage.connect(cfg.db_path)
        known_ids = storage.existing_product_ids(conn)
        conn.close()
    for it in items:
        it["inDb"] = str(it["productId"]) in known_ids

    collected = 0
    if collect:
        try:
            collected = _full_collect_resolved(client, cfg, items, progress)
        except RuntimeError as exc:
            err_console.print(f"[red]collect error:[/red] {exc}")

    captured_at = None
    if save_db:
        storage.init_db(cfg.db_path)
        captured_at = storage.save_search(cfg.db_path, query, items)

    organic = [it for it in items if not it["isAd"]]
    ads = [it for it in items if it["isAd"]]
    known = sum(1 for it in items if it["inDb"])
    if as_json:
        out_console.print_json(jsonlib.dumps({
            "query": query, "page": page, "url": result["url"],
            "capturedAt": captured_at or result["capturedAt"],
            "count": len(items), "organic": len(organic), "ads": len(ads),
            "inDb": known, "new": len(items) - known, "collected": collected, "items": items,
        }, ensure_ascii=False))
        return

    table = Table(title=f"search: {query} ({len(organic)} organic + {len(ads)} ads)")
    for col in ("#", "ad", "productId", "title", "price", "rating", "DB"):
        table.add_column(col)
    for it in items:
        table.add_row(
            str(it["rank"]), "AD" if it["isAd"] else "", str(it["productId"]),
            (it["title"] or "")[:36], f"{it['price']:,}" if it["price"] else "-",
            f"{it['ratingAverage']} ({it['reviewCount']})" if it["ratingAverage"] else "-",
            "✓" if it["inDb"] else "",
        )
    out_console.print(table)
    out_console.print(
        f"[green]{len(items)} results[/green] · 일반 {len(organic)} · 광고 {len(ads)} · "
        f"DB에 있음 {known} · 신규 {len(items) - known}"
    )
    if collect:
        out_console.print(f"[green]full-collected[/green] {collected} marketplace products")
    if save_db:
        out_console.print(f"[green]saved to DB[/green] {cfg.db_path.resolve()}")


@app.command("mint-cookies")
def mint_cookies_cmd(
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    config_path: Path | None = typer.Option(None, "--config"),
):
    """Force-refresh the browser-minted Akamai cookies (opens a brief headful Chrome window)."""
    from .cookies import cookie_path
    cfg = _build_config(db, config_path, None, None, None, None)
    client = CoupangClient(cfg)
    try:
        client.remint(progress=lambda m: err_console.print(f"[dim]· {m}[/dim]"))
    except RuntimeError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    out_console.print(f"[green]minted[/green] Akamai cookies → {cookie_path()}")


@app.command()
def dashboard(
    db: Path = typer.Option(Path.home() / ".coupang-sourcing" / "sourcing.db", "--db",
                            help="SQLite DB to visualize (default: the MCP/agent DB)."),
    port: int = typer.Option(8501, "--port"),
    headless: bool = typer.Option(False, "--headless", help="Don't auto-open a browser tab."),
):
    """Launch the Streamlit sourcing dashboard (visualize the DB + collect from the UI)."""
    import importlib.util
    import os
    import subprocess
    import sys
    try:
        import streamlit  # noqa: F401
    except ImportError:
        err_console.print("[red]streamlit not installed[/red] — run: uv pip install -e \".[dashboard]\"")
        raise typer.Exit(1) from None
    spec = importlib.util.find_spec("coupang_sourcing.dashboard")
    if not spec or not spec.origin:
        err_console.print("[red]dashboard module not found[/red]")
        raise typer.Exit(1)
    # Skip Streamlit's interactive first-run "Email:" prompt (it would block a headless launch).
    cred = Path.home() / ".streamlit" / "credentials.toml"
    if not cred.exists():
        cred.parent.mkdir(parents=True, exist_ok=True)
        cred.write_text('[general]\nemail = ""\n')
    env = {**os.environ, "COUPANG_SOURCING_DB": str(db)}
    out_console.print(f"[green]launching dashboard[/green] db={db} → http://localhost:{port}")
    cmd = [
        sys.executable, "-m", "streamlit", "run", spec.origin, "--server.port", str(port),
        # Force a light theme so text stays dark regardless of the user's global/system theme.
        "--theme.base", "light",
        "--theme.primaryColor", "#C81E2E",
        "--theme.backgroundColor", "#f4f6f9",
        "--theme.secondaryBackgroundColor", "#ffffff",
        "--theme.textColor", "#0f172a",
    ]
    if headless:
        cmd += ["--server.headless", "true"]
    subprocess.run(cmd, env=env)


@app.command()
def refresh(
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    config_path: Path | None = typer.Option(None, "--config"),
    store: str | None = typer.Option(None, "--store", help="Refresh only this store url-name."),
    all_products: bool = typer.Option(False, "--all", help="Refresh every product in the DB."),
    older_than: int | None = typer.Option(None, "--older-than", help="Only rows last crawled > N days ago."),
    rate: float | None = typer.Option(None, "--rate"),
    timeout: float | None = typer.Option(None, "--timeout"),
    retries: int | None = typer.Option(None, "--retries"),
    review_size: int | None = typer.Option(None, "--review-size"),
    fetch_reviews: bool = typer.Option(True, "--reviews/--no-reviews"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
    """Re-crawl existing DB products and append a new time-series snapshot."""
    if not (store or all_products or older_than is not None):
        err_console.print("[red]specify one of --store, --all, or --older-than[/red]")
        raise typer.Exit(1)
    cfg = _build_config(db, config_path, rate, timeout, retries, review_size)
    progress = _progress_fn(quiet)
    conn = storage.connect(cfg.db_path)
    targets = storage.list_products_for_refresh(conn, store=store, older_than_days=older_than)
    conn.close()
    if not targets:
        out_console.print("[yellow]no matching products to refresh[/yellow]")
        raise typer.Exit(0)

    client = CoupangClient(cfg)
    store_cache: dict[str, dict] = {}
    index_cache: dict[str, dict] = {}
    done = 0
    for row in targets:
        url_name = row["url_name"]
        pid = str(row["product_id"])
        if url_name not in store_cache:
            store_cache[url_name] = store_mod.resolve_store(client, url_name)
            index_cache[url_name] = store_mod.build_listing_index(
                client, store_cache[url_name], cfg, progress
            )
        variants = index_cache[url_name].get(pid)
        if not variants:
            if progress:
                progress(f"productId={pid} no longer in store {url_name} — skipped")
            continue
        conn = storage.connect(cfg.db_path)
        prior = storage.get_prior_snapshot(conn, pid)
        conn.close()
        ids = {"productId": pid, "itemId": row.get("item_id"),
               "vendorItemId": row.get("representative_vendor_item_id"), "sourceType": None, "link": None}
        record = product_mod.collect_product(
            client, ids, store_cache[url_name], cfg,
            fetch_reviews=fetch_reviews, prior_snapshot=prior, variants=variants, progress=progress,
        )
        storage.save_record(cfg.db_path, record)
        done += 1
    out_console.print(f"[green]refreshed[/green] {done}/{len(targets)} products → snapshots appended")


@app.command()
def export(
    table: str = typer.Option("products", "--table",
                              help="products | reviews | product_snapshots | product_variants | stores"),
    fmt: str = typer.Option("csv", "--format", help="csv | json"),
    out: Path | None = typer.Option(None, "--out", help="Output file (default coupang_<table>.<fmt>)."),
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    store: str | None = typer.Option(None, "--store", help="Filter products by store url-name."),
    min_score: float | None = typer.Option(None, "--min-score", help="Filter products by sourcing score."),
):
    """Export a DB table (or the products view) to CSV/JSON."""
    if fmt not in ("csv", "json"):
        err_console.print("[red]--format must be csv or json[/red]")
        raise typer.Exit(1)
    if not db.exists():
        err_console.print(f"[red]db not found:[/red] {db}")
        raise typer.Exit(1)
    try:
        path, count = exporters.export_table(db, table, fmt, out, store=store, min_score=min_score)
    except ValueError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc
    out_console.print(f"[green]exported[/green] {count} rows from '{table}' → {path}")


def _refresh_args_from(store: str | None, all_products: bool, older_than: int | None) -> list[str]:
    args: list[str] = []
    if all_products:
        args.append("--all")
    if store:
        args += ["--store", store]
    if older_than is not None:
        args += ["--older-than", str(older_than)]
    return args or ["--all"]


@schedule_app.command("install")
def schedule_install(
    interval: str = typer.Option("daily", "--interval", help="hourly | daily | weekly"),
    at: str | None = typer.Option(None, "--at", help="HH:MM for daily/weekly (default 03:00)."),
    db: Path = typer.Option(Path("coupang_sourcing.db"), "--db"),
    store: str | None = typer.Option(None, "--store", help="Refresh only this store."),
    all_products: bool = typer.Option(False, "--all", help="Refresh all (default if none given)."),
    older_than: int | None = typer.Option(None, "--older-than"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plist/cron line without installing."),
):
    """Install a launchd agent that runs `refresh` on a schedule."""
    if interval not in scheduler.INTERVALS:
        err_console.print(f"[red]--interval must be one of {scheduler.INTERVALS}[/red]")
        raise typer.Exit(1)
    refresh_args = _refresh_args_from(store, all_products, older_than)
    if not scheduler.is_macos():
        line = scheduler.crontab_line(refresh_args, db, interval, at)
        out_console.print("[yellow]not macOS[/yellow] — add this cron line manually (crontab -e):")
        typer.echo(line)
        raise typer.Exit(0)
    if dry_run:
        program = scheduler.build_program_args(refresh_args, db)
        typer.echo(scheduler.build_plist(program, interval, at))
        raise typer.Exit(0)
    path = scheduler.install(refresh_args, db, interval, at)
    out_console.print(f"[green]installed[/green] launchd agent → {path}")
    out_console.print(f"runs: refresh {' '.join(refresh_args)} ({interval}{' @' + at if at else ''})")


@schedule_app.command("uninstall")
def schedule_uninstall():
    """Remove the launchd agent."""
    if scheduler.uninstall():
        out_console.print("[green]uninstalled[/green] launchd agent")
    else:
        out_console.print("[yellow]no agent installed[/yellow]")


@schedule_app.command("status")
def schedule_status():
    """Show whether the schedule is installed and loaded."""
    info = scheduler.status()
    table = Table(show_header=False)
    table.add_column("field", style="cyan")
    table.add_column("value")
    for key in ("label", "installed", "loaded", "plist", "log"):
        table.add_row(key, str(info[key]))
    out_console.print(table)


if __name__ == "__main__":
    app()
