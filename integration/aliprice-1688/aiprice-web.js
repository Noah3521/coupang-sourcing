// AiPrice 웹사이트 이미지검색 (/Img/search_by_image) — HAR + search_detail.js 에서 추출
// sign = base64( AES-256-GCM( JSON.stringify({adid,page,page_size,filters,platform}), key=i_m_k, iv=i_m_v ) )
// Web Crypto 는 ciphertext 뒤에 16바이트 auth tag 를 붙인다 → Node 에서 동일 재현.
const crypto = require("crypto");

function b64decode(s) { return Buffer.from(s, "base64"); }
function b64(buf) { return Buffer.from(buf).toString("base64"); }

// Web Crypto AES-GCM 와 동일: 출력 = ciphertext || tag(16)
function aesGcmEncrypt(plaintext, keyB64, ivB64) {
  const key = b64decode(keyB64), iv = b64decode(ivB64);
  if (key.length !== 32) throw new Error("key must be 32 bytes, got " + key.length);
  if (iv.length !== 12) throw new Error("iv must be 12 bytes, got " + iv.length);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([cipher.update(Buffer.from(String(plaintext), "utf8")), cipher.final()]);
  const tag = cipher.getAuthTag();
  return b64(Buffer.concat([ct, tag]));
}

function makeSign(requestData, keyB64, ivB64) {
  return aesGcmEncrypt(JSON.stringify(requestData), keyB64, ivB64);
}

// provider → {adid, platform}
// adid 가 서버의 실제 라우팅 키. 아래 adid 는 search_detail.html 메뉴(data-adid)에서 확정.
// platform 문자열은 보조값(1688 캡처에서 platform:"1688" 확인).
// (* 표시는 이 HAR 메뉴에 없어 adid 미확정 — 셀렉트 후 캡처로 보강 필요)
const PROVIDERS = {
  "1688":        { adid: 100, platform: "1688" },        // ✔ HAR 응답으로 검증
  "taobao_lite": { adid: 221, platform: "taobao_lite" }, // ✔ 메뉴
  "aliexpress":  { adid: 18,  platform: "aliexpress" },  // ✔ 메뉴
  "domeggook":   { adid: 431, platform: "domeggook" },   // ✔ 메뉴
  "coupang":     { adid: 206, platform: "coupang" },     // ✔ 메뉴
  "amazon":      { adid: 23,  platform: "amazon" },
  "ebay":        { adid: 140, platform: "ebay" },
  "ozon":        { adid: 50,  platform: "ozon" },
  "netsea":      { adid: 336, platform: "netsea" },
  "ownerclan":   { adid: 461, platform: "ownerclan" },
  "onch3":       { adid: 603, platform: "onch3" },
  // adid 미확정 (다른 메뉴/구성에서 노출):
  "taobao":      { adid: null, platform: "taobao" },     // *
  "alibaba":     { adid: null, platform: "alibaba" },    // *
  "naver":       { adid: null, platform: "naver" },      // *
  "1688_pro":    { adid: null, platform: "1688_pro" },   // *
  "aliexpress_pro": { adid: null, platform: "aliexpress_pro" }, // *
};

async function searchByImage({ imageBase64, provider = "1688", page = 1, pageSize = 20,
                               filters = {}, adid, platform, key, iv, cookie = "" }) {
  const p = PROVIDERS[provider] || {};
  const requestData = {
    adid: String(adid ?? p.adid ?? 100),
    page,
    page_size: pageSize,
    filters,
    platform: platform ?? p.platform ?? provider,
  };
  const sign = makeSign(requestData, key, iv);
  const body = JSON.stringify({ sign, image: imageBase64 });

  const res = await fetch("https://www.aiprice.com/Img/search_by_image", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Origin": "https://www.aiprice.com",
      "Referer": "https://www.aiprice.com/img/search_detail.html",
      "X-Requested-With": "XMLHttpRequest",
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
      ...(cookie ? { Cookie: cookie } : {}),
    },
    body,
  });
  const text = await res.text();
  let json = null; try { json = JSON.parse(text); } catch {}
  return { status: res.status, json, text, requestData, sign };
}

module.exports = { searchByImage, makeSign, aesGcmEncrypt, PROVIDERS };
