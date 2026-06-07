"""coupang-sourcing CLI (Typer + Rich)."""
from __future__ import annotations

import json as jsonlib
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import storage
from .collectors import batch as batch_mod
from .collectors import product as product_mod
from .collectors import store as store_mod
from .config import Config
from .http_client import CoupangClient
from .models import ProductRecord
from .urls import parse_product, parse_store

app = typer.Typer(add_completion=False, help="Coupang product sourcing collector.")
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


if __name__ == "__main__":
    app()
