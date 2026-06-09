#!/usr/bin/env node
// Coupang → 1688 소싱 파이프라인
// 각 쿠팡 상품의 이미지로 aiprice 1688 이미지검색 → 상위 N개 원가 후보 → 메타데이터 수집
// → coupang sourcing.db 에 정규화 저장(쿠팡 상품에 귀속).
//
// 사용: node sourcing-pipeline.js [--db <path>] [--limit N] [--order score|recent]
//        [--product-id <id>] [--top 10] [--headless-top 3] [--no-headless]
//        [--resource] [--delay 800]
const fs = require("fs");
const path = require("path");
const os = require("os");
const { DatabaseSync } = require("node:sqlite");
const { searchByImage } = require("./aiprice-web");
const { enrichTopN, loadAipriceCookie, load1688Cookie, aesCreds } = require("./enrich-1688");

// ───────────────────────── args ─────────────────────────
function parseArgs(argv) {
  const a = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t.startsWith("--")) { const v = (argv[i + 1] && !argv[i + 1].startsWith("--")) ? argv[++i] : true; a[t.slice(2)] = v; }
    else a._.push(t);
  }
  return a;
}
const args = parseArgs(process.argv.slice(2));
const DB_PATH = args.db || process.env.COUPANG_SOURCING_DB || path.join(os.homedir(), ".coupang-sourcing", "sourcing.db");
const TOP = Number(args.top || 10);
const HEADLESS_TOP = args["no-headless"] ? 0 : Number(args["headless-top"] || 3);
const DELAY = Number(args.delay || 800);
const ORDER = args.order === "recent" ? "p.last_crawled DESC" : "p.sourcing_score DESC";

// ───────────────────────── coercion ─────────────────────────
const num = (x) => { if (x == null) return null; const n = parseFloat(x); return isNaN(n) ? null : n; };
const int = (x) => { if (x == null) return null; const n = parseInt(x, 10); return isNaN(n) ? null : n; };
const bool01 = (x) => (x ? 1 : 0);
const jstr = (x) => (x == null ? null : JSON.stringify(x));
function salesNum(s) {                       // "7500+", "10万+", "1.2万+", "<10"
  if (s == null) return null;
  if (typeof s === "number") return Math.round(s);
  let t = String(s).replace(/[+,\s]/g, "");
  if (!t || t[0] === "<") return null;
  let mul = 1;
  if (t.includes("万")) { mul = 10000; t = t.replace("万", ""); }
  const n = parseFloat(t);
  return isNaN(n) ? null : Math.round(n * mul);
}
function rate(x) {                            // "21.54%" → 0.2154, 0.668 → 0.668
  if (x == null) return null;
  if (typeof x === "number") return x;
  const s = String(x).trim();
  if (s.endsWith("%")) { const n = parseFloat(s); return isNaN(n) ? null : n / 100; }
  const n = parseFloat(s); return isNaN(n) ? null : n;
}
const nowISO = () => new Date().toISOString();

// ───────────────────────── schema ─────────────────────────
const DDL = `
CREATE TABLE IF NOT EXISTS sourcing_runs(
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, provider TEXT,
  params_json TEXT, products_total INTEGER, products_done INTEGER,
  products_failed INTEGER, offers_written INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS sourcing_product_status(
  coupang_product_id TEXT NOT NULL, run_id TEXT NOT NULL,
  status TEXT, offers_found INTEGER, image_url TEXT, error TEXT, sourced_at TEXT,
  PRIMARY KEY(coupang_product_id, run_id));
CREATE INDEX IF NOT EXISTS idx_src_status_product ON sourcing_product_status(coupang_product_id);
CREATE TABLE IF NOT EXISTS s1688_offers(
  match_id TEXT PRIMARY KEY, coupang_product_id TEXT NOT NULL, offer_id TEXT NOT NULL,
  rank INTEGER, run_id TEXT, title TEXT, detail_url TEXT, image TEXT, ori_image TEXT,
  price_cny REAL, price_converted REAL, price_min_cny REAL, price_max_cny REAL,
  month_sold INTEGER, last30d_sales INTEGER, total_sales INTEGER, total_order INTEGER,
  repurchase_rate REAL, collection_rate_24h REAL, good_rates REAL, remark_cnt INTEGER,
  moq INTEGER, moq_headless INTEGER, stock INTEGER, shipping_time_guarantee TEXT,
  category TEXT, category_name TEXT, earliest_listing_time TEXT, latest_update_time TEXT, create_date TEXT,
  video_url TEXT, detail_ret TEXT, headless_done INTEGER, headless_captcha INTEGER, headless_specs_cnt INTEGER,
  sourced_at TEXT, UNIQUE(coupang_product_id, offer_id));
CREATE INDEX IF NOT EXISTS idx_s1688_offers_product ON s1688_offers(coupang_product_id);
CREATE INDEX IF NOT EXISTS idx_s1688_offers_offer   ON s1688_offers(offer_id);
CREATE TABLE IF NOT EXISTS s1688_shop(
  match_id TEXT PRIMARY KEY, shop_name TEXT, shop_url TEXT, customerstar REAL, tpyear INTEGER,
  superfactory INTEGER, opened_year TEXT, wangwang TEXT, is_blacklist INTEGER,
  rdf_rate REAL, goods_rate REAL, lgt_rate REAL, dspt_rate REAL, cst_rate REAL,
  pay_num_30d INTEGER, response_rate_30d REAL, quality_rate_30d REAL,
  collect_48h_rate_30d REAL, fulfill_rate_30d REAL, mord_dspt_rate_30d REAL);
CREATE TABLE IF NOT EXISTS s1688_price_history(
  match_id TEXT NOT NULL, date TEXT, max_price REAL, min_price REAL,
  max_price_qty INTEGER, min_price_qty INTEGER, trade_count INTEGER, PRIMARY KEY(match_id, date));
CREATE TABLE IF NOT EXISTS s1688_sales_history(
  match_id TEXT NOT NULL, date TEXT, sale_quantity REAL, PRIMARY KEY(match_id, date));
CREATE TABLE IF NOT EXISTS s1688_sale_ranges(
  match_id TEXT NOT NULL, date TEXT, max_price REAL, min_price REAL, PRIMARY KEY(match_id, date));
CREATE TABLE IF NOT EXISTS s1688_price_ladder(
  match_id TEXT NOT NULL, tier INTEGER, qty_from INTEGER, qty_to INTEGER, price REAL, PRIMARY KEY(match_id, tier));
CREATE TABLE IF NOT EXISTS s1688_sku(
  match_id TEXT NOT NULL, prop_fid INTEGER, prop_name TEXT, value_idx INTEGER,
  value_name TEXT, value_image TEXT, PRIMARY KEY(match_id, prop_name, value_name));
CREATE TABLE IF NOT EXISTS s1688_specs(
  match_id TEXT NOT NULL, spec_key TEXT, spec_value TEXT, PRIMARY KEY(match_id, spec_key));
CREATE TABLE IF NOT EXISTS s1688_gallery(
  match_id TEXT NOT NULL, idx INTEGER, url TEXT, PRIMARY KEY(match_id, idx));
CREATE TABLE IF NOT EXISTS s1688_identities(
  match_id TEXT NOT NULL, kind TEXT, value TEXT, PRIMARY KEY(match_id, kind, value));
`;

// ───────────────────────── image download ─────────────────────────
async function downloadImageBase64(url) {
  const ac = new AbortController();
  const to = setTimeout(() => ac.abort(), 15000);
  try {
    const res = await fetch(url, {
      signal: ac.signal,
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Referer": "https://www.coupang.com/",
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
      },
    });
    const ct = res.headers.get("content-type") || "";
    if (!res.ok || !/image\//.test(ct)) throw new Error(`HTTP ${res.status} ${ct}`);
    const buf = Buffer.from(await res.arrayBuffer());
    return buf.toString("base64");
  } finally { clearTimeout(to); }
}

// ───────────────────────── DB writes ─────────────────────────
function writeOffers(db, coupangId, runId, offers) {
  const upOffer = db.prepare(`INSERT INTO s1688_offers(
    match_id,coupang_product_id,offer_id,rank,run_id,title,detail_url,image,ori_image,
    price_cny,price_converted,price_min_cny,price_max_cny,month_sold,last30d_sales,total_sales,total_order,
    repurchase_rate,collection_rate_24h,good_rates,remark_cnt,moq,moq_headless,stock,shipping_time_guarantee,
    category,category_name,earliest_listing_time,latest_update_time,create_date,video_url,
    detail_ret,headless_done,headless_captcha,headless_specs_cnt,sourced_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(match_id) DO UPDATE SET
      rank=excluded.rank,run_id=excluded.run_id,title=excluded.title,detail_url=excluded.detail_url,
      image=excluded.image,ori_image=excluded.ori_image,price_cny=excluded.price_cny,price_converted=excluded.price_converted,
      price_min_cny=excluded.price_min_cny,price_max_cny=excluded.price_max_cny,month_sold=excluded.month_sold,
      last30d_sales=excluded.last30d_sales,total_sales=excluded.total_sales,total_order=excluded.total_order,
      repurchase_rate=excluded.repurchase_rate,collection_rate_24h=excluded.collection_rate_24h,good_rates=excluded.good_rates,
      remark_cnt=excluded.remark_cnt,moq=excluded.moq,moq_headless=excluded.moq_headless,stock=excluded.stock,
      shipping_time_guarantee=excluded.shipping_time_guarantee,category=excluded.category,category_name=excluded.category_name,
      earliest_listing_time=excluded.earliest_listing_time,latest_update_time=excluded.latest_update_time,create_date=excluded.create_date,
      video_url=excluded.video_url,detail_ret=excluded.detail_ret,headless_done=excluded.headless_done,
      headless_captcha=excluded.headless_captcha,headless_specs_cnt=excluded.headless_specs_cnt,sourced_at=excluded.sourced_at`);
  const upShop = db.prepare(`INSERT INTO s1688_shop(
    match_id,shop_name,shop_url,customerstar,tpyear,superfactory,opened_year,wangwang,is_blacklist,
    rdf_rate,goods_rate,lgt_rate,dspt_rate,cst_rate,pay_num_30d,response_rate_30d,quality_rate_30d,
    collect_48h_rate_30d,fulfill_rate_30d,mord_dspt_rate_30d)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(match_id) DO UPDATE SET shop_name=excluded.shop_name,shop_url=excluded.shop_url,
      customerstar=excluded.customerstar,tpyear=excluded.tpyear,superfactory=excluded.superfactory,
      opened_year=excluded.opened_year,wangwang=excluded.wangwang,is_blacklist=excluded.is_blacklist,
      rdf_rate=excluded.rdf_rate,goods_rate=excluded.goods_rate,lgt_rate=excluded.lgt_rate,dspt_rate=excluded.dspt_rate,
      cst_rate=excluded.cst_rate,pay_num_30d=excluded.pay_num_30d,response_rate_30d=excluded.response_rate_30d,
      quality_rate_30d=excluded.quality_rate_30d,collect_48h_rate_30d=excluded.collect_48h_rate_30d,
      fulfill_rate_30d=excluded.fulfill_rate_30d,mord_dspt_rate_30d=excluded.mord_dspt_rate_30d`);
  const delChild = (t) => db.prepare(`DELETE FROM ${t} WHERE match_id=?`);
  const dels = ["s1688_price_history", "s1688_sales_history", "s1688_sale_ranges", "s1688_price_ladder", "s1688_sku", "s1688_specs", "s1688_gallery", "s1688_identities"].map(delChild);
  const insPH = db.prepare(`INSERT OR REPLACE INTO s1688_price_history(match_id,date,max_price,min_price,max_price_qty,min_price_qty,trade_count) VALUES(?,?,?,?,?,?,?)`);
  const insSH = db.prepare(`INSERT OR REPLACE INTO s1688_sales_history(match_id,date,sale_quantity) VALUES(?,?,?)`);
  const insSR = db.prepare(`INSERT OR REPLACE INTO s1688_sale_ranges(match_id,date,max_price,min_price) VALUES(?,?,?,?)`);
  const insPL = db.prepare(`INSERT OR REPLACE INTO s1688_price_ladder(match_id,tier,qty_from,qty_to,price) VALUES(?,?,?,?,?)`);
  const insSKU = db.prepare(`INSERT OR REPLACE INTO s1688_sku(match_id,prop_fid,prop_name,value_idx,value_name,value_image) VALUES(?,?,?,?,?,?)`);
  const insSpec = db.prepare(`INSERT OR REPLACE INTO s1688_specs(match_id,spec_key,spec_value) VALUES(?,?,?)`);
  const insGal = db.prepare(`INSERT OR REPLACE INTO s1688_gallery(match_id,idx,url) VALUES(?,?,?)`);
  const insId = db.prepare(`INSERT OR REPLACE INTO s1688_identities(match_id,kind,value) VALUES(?,?,?)`);

  db.exec("BEGIN");
  try {
    let written = 0;
    offers.forEach((m, i) => {
      if (!m || m.offerId == null) return;
      const matchId = `${coupangId}:${m.offerId}`;
      const rank = i + 1;
      const hl = m._headless && !m._headless.err;
      upOffer.run(
        matchId, coupangId, String(m.offerId), rank, runId, m.title ?? null, m.detailUrl ?? null,
        m.image ?? null, m.ori_image ?? null,
        num(m.price_cny), num(m.price_converted), num(m.minPrice), num(m.maxPrice),
        int(m.monthSold), salesNum(m.last30DaysSales), salesNum(m.totalSales), salesNum(m.totalOrder),
        rate(m.repurchaseRate), rate(m.collectionRate24h), num(m.goodRates), int(m.remarkCnt),
        int(m.minOrderQuantity), int(m.moq2), int(m.stock), m.shippingTimeGuarantee ?? null,
        m.category ?? null, m.categoryName ?? null, m.earliestListingTime ?? null, m.latestUpdateTime ?? null, m.createDate ?? null,
        m.video ?? null, m._detailRet ?? null, bool01(hl), bool01(m._headless && m._headless.captcha), int(m._headless && m._headless.specs),
        nowISO()
      );
      // shop
      const s = m.shop || {};
      upShop.run(matchId, s.shop_name ?? null, s.shop_url ?? null, num(s.customerstar), int(s.tpyear), int(s.superfactory),
        s.opened_year ?? null, s.wangwang ?? null, int(s.is_blacklist),
        num(s.rdf_group_value_new), num(s.goods_group_value), num(s.lgt_group_value_new), num(s.dspt_group_value), num(s.cst_group_value_new),
        int(s.shop_pay_num_30d), num(s.shop_response_rate_30d), num(s.shop_quality_rate_30d),
        num(s.shop_collect_48h_rate_30d), num(s.shop_fulfill_rate_30d), num(s.shop_mord_dspt_rate_30d));
      // child: clear then insert
      dels.forEach((d) => d.run(matchId));
      (m.priceHistory || []).forEach((r) => insPH.run(matchId, String(r.date), num(r.maxPrice), num(r.minPrice), int(r.maxPriceQuantity), int(r.minPriceQuantity), int(r.tradeCount)));
      (m.salesHistory || []).forEach((r) => insSH.run(matchId, String(r.date), num(r.saleQuantity)));
      (m.saleRangeList || []).forEach((r) => insSR.run(matchId, String(r.date), num(r.maxPrice), num(r.minPrice)));
      (m.priceLadder || []).forEach((r, ti) => insPL.run(matchId, ti, int(r.from), int(r.to), num(r.price)));
      (m.sku || []).forEach((p) => (p.value || []).forEach((v, vi) => insSKU.run(matchId, int(p.fid), p.prop ?? null, vi, v.name ?? null, v.imageUrl ?? null)));
      if (m.specs) for (const [k, v] of Object.entries(m.specs)) insSpec.run(matchId, k, v == null ? null : String(v));
      (m.gallery || []).forEach((u, gi) => insGal.run(matchId, gi, u));
      (m.sellerIdentities || []).forEach((v) => insId.run(matchId, "seller", String(v)));
      (m.offerIdentities || []).forEach((v) => insId.run(matchId, "offer", String(v)));
      written++;
    });
    db.exec("COMMIT");
    return written;
  } catch (e) { db.exec("ROLLBACK"); throw e; }
}

// ───────────────────────── product selection / image ─────────────────────────
function selectProducts(db) {
  if (args["product-id"]) {
    return db.prepare(`SELECT product_id, representative_vendor_item_id, title, sourcing_score FROM products WHERE product_id=?`).all(String(args["product-id"]));
  }
  let sql = `SELECT p.product_id, p.representative_vendor_item_id, p.title, p.sourcing_score
             FROM products p`;
  if (!args.resource) sql += ` WHERE NOT EXISTS (SELECT 1 FROM sourcing_product_status s WHERE s.coupang_product_id=p.product_id AND s.status='ok')`;
  sql += ` ORDER BY ${ORDER}`;
  if (args.limit) sql += ` LIMIT ${Number(args.limit)}`;
  return db.prepare(sql).all();
}
function resolveImageUrl(db, product) {
  if (product.representative_vendor_item_id) {
    const r = db.prepare(`SELECT image FROM product_variants WHERE vendor_item_id=?`).get(String(product.representative_vendor_item_id));
    if (r && r.image) return r.image;
  }
  const r = db.prepare(`SELECT image FROM product_variants WHERE product_id=? AND image IS NOT NULL AND image!='' ORDER BY vendor_item_id LIMIT 1`).get(String(product.product_id));
  return r ? r.image : null;
}
function markStatus(db, coupangId, runId, status, extra = {}) {
  db.prepare(`INSERT INTO sourcing_product_status(coupang_product_id,run_id,status,offers_found,image_url,error,sourced_at)
    VALUES(?,?,?,?,?,?,?)
    ON CONFLICT(coupang_product_id,run_id) DO UPDATE SET status=excluded.status,offers_found=excluded.offers_found,
      image_url=excluded.image_url,error=excluded.error,sourced_at=excluded.sourced_at`)
    .run(coupangId, runId, status, extra.offers_found ?? null, extra.image_url ?? null, extra.error ?? null, nowISO());
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ───────────────────────── main ─────────────────────────
(async () => {
  if (!fs.existsSync(DB_PATH)) { console.error("DB 없음:", DB_PATH); process.exit(1); }
  const db = new DatabaseSync(DB_PATH);
  db.exec(DDL);

  const cookieA = loadAipriceCookie();
  const { key, iv } = aesCreds(cookieA);
  const cookie1688 = load1688Cookie();
  if (!key || !iv) { console.error("aiprice 쿠키(i_m_k/i_m_v) 없음 — decrypt-cookies.js 실행 필요"); process.exit(1); }

  const products = selectProducts(db);
  if (!products.length) { console.error("대상 상품 없음 (이미 소싱됨? --resource 로 재소싱)"); process.exit(0); }

  const runId = nowISO().replace(/[:.]/g, "-");
  const params = { top: TOP, headlessTop: HEADLESS_TOP, order: ORDER, limit: args.limit || null, resource: !!args.resource };
  db.prepare(`INSERT INTO sourcing_runs(run_id,started_at,provider,params_json,products_total,products_done,products_failed,offers_written,status)
    VALUES(?,?,?,?,?,0,0,0,'running')`).run(runId, nowISO(), "1688", JSON.stringify(params), products.length);

  console.error(`▶ run ${runId} | 대상 ${products.length}개 | top${TOP} headless상위${HEADLESS_TOP} | DB ${DB_PATH}`);
  let browser = null;
  if (HEADLESS_TOP > 0) { const { chromium } = require("playwright"); browser = await chromium.launch({ headless: true }); }

  let done = 0, failed = 0, offersWritten = 0, abort = false;
  for (let pi = 0; pi < products.length && !abort; pi++) {
    const p = products[pi];
    const tag = `[${pi + 1}/${products.length}] ${p.product_id} ${String(p.title || "").slice(0, 24)}`;
    try {
      const imageUrl = resolveImageUrl(db, p);
      if (!imageUrl) { markStatus(db, p.product_id, runId, "no_image"); console.error(`${tag} → no_image`); failed++; continue; }
      let imageBase64;
      try { imageBase64 = await downloadImageBase64(imageUrl); }
      catch (e) { markStatus(db, p.product_id, runId, "image_failed", { image_url: imageUrl, error: String(e).slice(0, 120) }); console.error(`${tag} → image_failed (${e.message})`); failed++; continue; }

      const sr = await searchByImage({ imageBase64, provider: "1688", pageSize: Math.max(TOP, 10), key, iv, cookie: cookieA });
      if (!sr.json) { markStatus(db, p.product_id, runId, "search_failed", { image_url: imageUrl, error: (sr.text || "").slice(0, 120) }); console.error(`${tag} → search_failed`); failed++; continue; }
      if (sr.json.code !== 0) {
        markStatus(db, p.product_id, runId, "not_login", { image_url: imageUrl, error: JSON.stringify(sr.json).slice(0, 120) });
        console.error(`${tag} → not_login/quota (code ${sr.json.code}) — 쿠키 만료 의심, 런 중단`);
        abort = true; continue;
      }
      const items = (sr.json.data || []).slice(0, TOP);
      if (!items.length) { markStatus(db, p.product_id, runId, "search_empty", { image_url: imageUrl, offers_found: 0 }); console.error(`${tag} → search_empty`); done++; continue; }

      const offers = await enrichTopN(items, { browser, cookie1688, top: TOP, headlessTop: HEADLESS_TOP });
      const w = writeOffers(db, p.product_id, runId, offers);
      offersWritten += w;
      markStatus(db, p.product_id, runId, "ok", { image_url: imageUrl, offers_found: offers.length });
      const hl = offers.filter((o) => o._headless && !o._headless.err).length;
      console.error(`${tag} → ok | offers ${w} (headless ${hl})`);
      done++;
      if (pi < products.length - 1) await sleep(DELAY + Math.floor(Math.random() * DELAY));
    } catch (e) {
      markStatus(db, p.product_id, runId, "error", { error: String(e).slice(0, 160) });
      console.error(`${tag} → error: ${e.message}`); failed++;
    }
  }
  if (browser) await browser.close();

  db.prepare(`UPDATE sourcing_runs SET finished_at=?,products_done=?,products_failed=?,offers_written=?,status=? WHERE run_id=?`)
    .run(nowISO(), done, failed, offersWritten, abort ? "aborted" : "completed", runId);
  console.error(`■ run ${abort ? "ABORTED" : "completed"} | done ${done} fail ${failed} | offers ${offersWritten}`);
  db.close();
})();
