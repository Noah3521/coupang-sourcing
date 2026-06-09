#!/usr/bin/env node
// 1688 이미지검색 top-N → 각 상품의 가능한 모든 메타데이터 수집
//   소스1: search_by_image 결과(제목/가격/이미지/판매량/재구매율/판매자 shop 지표)
//   소스2: mtop.1688.pc.plugin.od.data.query (카테고리/등록일/평점/일별 판매·가격 이력/총판매)
//   소스3: (옵션) 헤드리스 상세 — SKU·사양표·계단식가격·재고·영상·갤러리
// 사용: node enrich-1688.js <이미지> [--top 5] [--headless] [--headless-top N] [--out result.json]
const fs = require("fs");
const path = require("path");
const { searchByImage } = require("./aiprice-web");
const { fetchOfferDetail } = require("./detail-1688");
const { scrapeOffer } = require("./headless-1688");

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : def;
}

// ── 쿠키 헬퍼 (파이프라인과 공유) ──
function sanitizeCookie(raw) {
  return (raw || "").split(/;\s*/).filter(Boolean).filter(p => /^[\x20-\x7e]*$/.test(p)).join("; ");
}
function loadAipriceCookie() {
  const f = path.join(__dirname, "cookie.txt");
  const raw = fs.existsSync(f) ? fs.readFileSync(f, "utf8").trim() : (process.env.AIPRICE_COOKIE || "");
  return sanitizeCookie(raw);
}
function load1688Cookie() {
  const f = path.join(__dirname, "cookie.1688.txt");
  return fs.existsSync(f) ? sanitizeCookie(fs.readFileSync(f, "utf8").trim()) : "";
}
function ck(cookie, name) {
  const m = (cookie || "").match(new RegExp("(?:^|;\\s*)" + name + "=([^;]+)"));
  return m ? decodeURIComponent(m[1]) : null;
}
function aesCreds(cookie) {
  return { key: ck(cookie, "i_m_k"), iv: ck(cookie, "i_m_v") };
}

// ── 단일 오퍼 병합: search item + mtop detail + (옵션) headless ──
async function enrichOffer(it, { browser = null, cookie1688 = "", doHeadless = false } = {}) {
  const offerId = it.sku_id;
  let detail = null, detailRet = null;
  try {
    const d = await fetchOfferDetail(offerId, { cookie: cookie1688 });
    detailRet = d.ret; detail = d.data;
  } catch (e) { detailRet = "ERR:" + e.message; }

  const merged = {
    offerId,
    title: it.title,
    detailUrl: `https://detail.1688.com/offer/${offerId}.html`,
    // ── 가격 ──
    price_cny: it.price,
    price_converted: it.cur_price,
    priceHistory: detail?.tradePriceList || null,   // 일별 가격
    // ── 판매/평점 ──
    monthSold: it.monthSold,
    last30DaysSales: detail?.last30DaysSales,
    last30DaysDropShippingSales: detail?.last30DaysDropShippingSales,
    totalSales: detail?.totalSales,
    totalOrder: detail?.totalOrder,
    salesHistory: detail?.saleQuantityList || null, // 일별 판매량
    saleRangeList: detail?.saleRangeList || null,
    repurchaseRate: detail?.repurchaseRate ?? it.repurchaseRate,
    collectionRate24h: detail?.collectionRate24h,
    goodRates: detail?.goodRates,
    remarkCnt: detail?.remarkCnt,
    // ── 분류/시간 ──
    category: detail?.categoryListName,
    categoryName: detail?.categoryName,
    earliestListingTime: detail?.earliestListingTime,
    latestUpdateTime: detail?.latestUpdateTime,
    createDate: it.createDate,
    // ── 거래조건 ──
    minOrderQuantity: it.minOrderQuantity,
    shippingTimeGuarantee: it.shippingTimeGuarantee,
    sellerIdentities: it.sellerIdentities,
    offerIdentities: it.offerIdentities,
    // ── 이미지 ──
    image: it.picture,
    ori_image: it.ori_picture,
    // ── 판매자/상점 ──
    shop: it.shops || null,
    // ── 메타 ──
    _detailRet: detailRet,
  };

  // (옵션) 헤드리스로 SKU·사양표·계단식가격·재고·영상·갤러리
  if (browser && doHeadless) {
    try {
      const h = await scrapeOffer(offerId, { browser });
      merged.sku = h.skuModel?.skuProps || null;
      merged.specs = h.attributes || null;
      merged.priceLadder = h.priceRanges || null;
      merged.stock = h.stock;
      merged.moq2 = h.moq;
      merged.minPrice = h.minPrice ?? null;
      merged.maxPrice = h.maxPrice ?? null;
      merged.priceRange = (h.minPrice && h.maxPrice) ? `¥${h.minPrice}~¥${h.maxPrice}` : null;
      merged.video = h.video?.url || null;
      merged.gallery = h.images || null;
      merged._headless = { specs: Object.keys(h.attributes || {}).length, sku: (h.skuModel?.skuProps || []).length, captcha: h.captcha };
    } catch (e) { merged._headless = { err: String(e).slice(0, 120) }; }
  }
  return merged;
}

// ── top-N 루프: 브라우저 1개 공유, rank<=headlessTop 만 헤드리스 ──
async function enrichTopN(items, { browser = null, cookie1688 = "", top = items.length, headlessTop = 0, onProgress } = {}) {
  const list = items.slice(0, top);
  const out = [];
  for (let i = 0; i < list.length; i++) {
    const doHeadless = !!browser && i < headlessTop;
    let merged;
    try {
      merged = await enrichOffer(list[i], { browser, cookie1688, doHeadless });
    } catch (e) {
      merged = { offerId: list[i].sku_id, title: list[i].title, _error: String(e).slice(0, 160) };
    }
    out.push(merged);
    if (onProgress) onProgress(i, list.length, merged);
  }
  return out;
}

module.exports = { enrichOffer, enrichTopN, loadAipriceCookie, load1688Cookie, ck, aesCreds, sanitizeCookie };

// ── CLI (얇은 래퍼) ──
if (require.main === module) {
  (async () => {
    const imgPath = process.argv[2];
    if (!imgPath || imgPath.startsWith("--")) { console.error("usage: node enrich-1688.js <image> [--top 5] [--headless] [--headless-top N] [--out file.json]"); process.exit(1); }
    const TOP = Number(arg("top", 5));
    const useHeadless = process.argv.includes("--headless");
    const headlessTop = Number(arg("headless-top", useHeadless ? TOP : 0));
    const cookie = loadAipriceCookie();
    const { key, iv } = aesCreds(cookie);

    const imageBase64 = fs.readFileSync(imgPath).toString("base64");
    const sr = await searchByImage({ imageBase64, provider: "1688", pageSize: Math.max(TOP, 10), key, iv, cookie });
    if (!sr.json || sr.json.code !== 0) { console.error("search failed:", JSON.stringify(sr.json)); process.exit(2); }
    const items = (sr.json.data || []).slice(0, TOP);
    console.error(`검색 ${sr.json.data.length}건 → 상위 ${items.length}건 상세 수집${headlessTop ? ` (+헤드리스 상위${headlessTop})` : ""}...`);

    let browser = null;
    if (headlessTop > 0) { const { chromium } = require("playwright"); browser = await chromium.launch({ headless: true }); }

    const out = await enrichTopN(items, {
      browser, cookie1688: load1688Cookie(), top: TOP, headlessTop,
      onProgress: (i, n, m) => console.error(`  [${i + 1}/${n}] ${m.offerId}  ${m._detailRet || ""}${m._headless ? "  sku:" + m._headless.sku + " specs:" + m._headless.specs : ""}  ${String(m.title).slice(0, 28)}`),
    });
    if (browser) await browser.close();

    const outFile = arg("out", null);
    if (outFile) { fs.writeFileSync(outFile, JSON.stringify(out, null, 2)); console.error("→ saved", outFile); }
    else console.log(JSON.stringify(out, null, 2));
  })();
}
