// 1688 상세 페이지 헤드리스 스크래퍼 — SKU·사양표·가격대·이미지갤러리 추출 (baxia 우회)
// 사용: node headless-1688.js <offerId> [--show]
//   또는 모듈: const {scrapeOffer}=require("./headless-1688"); await scrapeOffer(id,{browser})
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

function loadCookies(file, domains) {
  if (!fs.existsSync(file)) return [];
  const raw = fs.readFileSync(file, "utf8").trim(); const out = [];
  for (const p of raw.split(/;\s*/).filter(Boolean)) {
    const i = p.indexOf("="); const name = p.slice(0, i), value = p.slice(i + 1);
    if (!/^[\x20-\x7e]*$/.test(value)) continue;
    for (const d of domains) out.push({ name, value, domain: d, path: "/" });
  }
  return out;
}

// 페이지 컨텍스트에서 실행될 추출 함수
function extractInPage() {
  const out = { skuModel: null, attributes: {}, priceRanges: [], images: [], title: null, source: {} };

  // 균형 중괄호로 임베디드 JSON 추출
  function extractJSON(html, key) {
    const i = html.indexOf('"' + key + '":');
    if (i < 0) return null;
    const s = html.indexOf("{", i);
    if (s < 0) return null;
    let depth = 0, inStr = false, esc = false;
    for (let j = s; j < html.length; j++) {
      const c = html[j];
      if (esc) { esc = false; continue; }
      if (c === "\\") { esc = true; continue; }
      if (c === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (c === "{") depth++;
      else if (c === "}") { depth--; if (depth === 0) return html.slice(s, j + 1); }
    }
    return null;
  }

  const html = document.documentElement.innerHTML;

  // 1) SKU
  try {
    const raw = extractJSON(html, "skuModel");
    if (raw) out.skuModel = JSON.parse(raw);
    out.source.skuModel = raw ? "embedded" : "none";
  } catch (e) { out.source.skuErr = String(e); }

  // 2) 사양표 (#productAttributes의 ant-descriptions)
  try {
    const rows = [...document.querySelectorAll("#productAttributes tr.ant-descriptions-row, #productAttributes .ant-descriptions-row")];
    for (const r of rows) {
      const labels = [...r.querySelectorAll(".ant-descriptions-item-label")];
      const contents = [...r.querySelectorAll(".ant-descriptions-item-content")];
      for (let k = 0; k < labels.length; k++) {
        const key = labels[k].textContent.trim();
        const val = (contents[k] ? contents[k].textContent : "").trim();
        if (key) out.attributes[key] = val;
      }
    }
    out.source.attributes = Object.keys(out.attributes).length;
  } catch (e) { out.source.attrErr = String(e); }

  // 3) 가격대(계단식)·거래조건 — 임베디드 priceModel/tradeModel (깔끔)
  try {
    const pm = extractJSON(html, "priceModel");
    if (pm) { const o = JSON.parse(pm); out.priceLadder = o.currentPrices || []; out.priceDisplayType = o.priceDisplayType; }
    const tm = extractJSON(html, "tradeModel");
    if (tm) {
      const o = JSON.parse(tm);
      out.priceRanges = (o.disPriceRanges || []).map(r => ({ from: r.beginAmount, to: r.endAmount || null, price: r.discountPrice || r.price }));
      out.minPrice = o.minPrice; out.maxPrice = o.maxPrice;
      out.stock = o.canBookedAmount;
      out.moq = o.beginAmount;
      out.mix = o.mixModel || null;
    }
  } catch (e) { out.source.priceErr = String(e); }

  // 3b) 상품 영상
  try {
    const vid = extractJSON(html, "offerImgList");
    if (vid) { const o = JSON.parse(vid); if (o.videoUrl) out.video = { url: o.videoUrl, cover: o.coverUrl, id: o.videoId }; }
  } catch (e) {}

  // 4) 이미지 갤러리
  try {
    const imgs = new Set();
    document.querySelectorAll('[class*="gallery"] img, [class*="detail-gallery"] img, [class*="od-gallery"] img, [id*="mainPic"] img, [class*="preview"] img').forEach(im => {
      let s = im.getAttribute("src") || im.getAttribute("data-src") || "";
      s = s.replace(/_\d+x\d+\.(jpg|png|webp).*$/i, ""); // 썸네일 접미사 제거
      if (/alicdn\.com/.test(s)) imgs.add(s.split("?")[0]);
    });
    out.images = [...imgs].slice(0, 30);
  } catch (e) {}

  // 5) 제목
  out.title = (document.querySelector('[class*="title"] [class*="text"], h1, [class*="od-pc-offer-title"]') || {}).textContent?.trim()
    || document.title.replace(/ - 阿里巴巴.*$/, "");

  // 6) window 전역 데이터(있으면)
  try { if (window.offer_details) out.source.hasOfferDetailsGlobal = true; } catch (e) {}
  return out;
}

async function scrapeOffer(offerId, { browser, langZh = true } = {}) {
  const own = !browser;
  if (own) browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    locale: langZh ? "zh-CN" : "ko-KR",
  });
  await ctx.addCookies(loadCookies(path.join(__dirname, "cookie.1688.txt"), [".1688.com", ".taobao.com"]));
  const page = await ctx.newPage();
  let captcha = false;
  try {
    await page.goto(`https://detail.1688.com/offer/${offerId}.html`, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForSelector("#productAttributes, [data-module='od_product_attributes']", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const t = await page.title();
    captcha = /验证|滑块|punish/i.test(t) || !t;
  } catch (e) { /* nav timeout */ }
  const data = await page.evaluate(extractInPage).catch(() => null);
  await ctx.close();
  if (own) await browser.close();
  return { offerId, captcha, ...(data || {}) };
}

module.exports = { scrapeOffer };

if (require.main === module) {
  (async () => {
    const offerId = process.argv[2];
    if (!offerId) { console.error("usage: node headless-1688.js <offerId>"); process.exit(1); }
    const r = await scrapeOffer(offerId);
    // 요약 출력
    console.log("title:", r.title);
    console.log("captcha:", r.captcha, "| source:", JSON.stringify(r.source));
    if (r.skuModel?.skuProps) {
      console.log("\n=== SKU ===");
      for (const p of r.skuModel.skuProps) {
        console.log(`  ${p.prop}: ${(p.value || []).map(v => v.name).join(", ")}`);
      }
    }
    console.log("\n=== 사양표(" + Object.keys(r.attributes).length + ") ===");
    for (const [k, v] of Object.entries(r.attributes)) console.log(`  ${k}: ${v}`);
    console.log("\n=== 계단식 가격 ===");
    for (const t of (r.priceRanges || [])) console.log(`  ${t.from}${t.to ? "-" + t.to : "+"}개: ¥${t.price}`);
    console.log(`  최소주문 ${r.moq} | 재고 ${r.stock} | 가격범위 ¥${r.minPrice}~¥${r.maxPrice}`);
    if (r.video) console.log("  영상:", r.video.url);
    console.log("\n=== 이미지(" + r.images.length + ") ===\n  " + r.images.slice(0, 5).join("\n  "));
    if (process.argv.includes("--json")) fs.writeFileSync(`offer_${offerId}.json`, JSON.stringify(r, null, 2));
  })();
}
