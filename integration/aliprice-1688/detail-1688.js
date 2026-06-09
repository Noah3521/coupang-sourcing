// 1688 offer 상세 메타데이터 — 확장이 쓰는 mtop API 그대로 재현
// API: mtop.1688.pc.plugin.od.data.query  @ acs.m.taobao.com
// sign = md5( token & t & appKey & data ),  token = _m_h5_tk 쿠키 split('_')[0]
// 토큰 프라이밍: 첫 호출 FAIL_SYS_TOKEN_EMPTY → 응답 set-cookie 의 _m_h5_tk 로 재시도
const crypto = require("crypto");

const APP_KEY = 12574478;
const API = "mtop.1688.pc.plugin.od.data.query";
const BASE = `https://acs.m.taobao.com/h5/${API}/1.0/`;
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36";

const md5 = (s) => crypto.createHash("md5").update(s, "utf8").digest("hex");

function buildUrl(token, data) {
  const t = Date.now();
  const sign = md5(`${token}&${t}&${APP_KEY}&${data}`);
  const q = new URLSearchParams({
    jsv: "2.7.3", appKey: String(APP_KEY), t: String(t), sign,
    api: API, v: "1.0", type: "originaljson", dataType: "json", data,
  });
  return `${BASE}?${q}`;
}

function mergeSetCookies(res, jar) {
  const all = res.headers.getSetCookie ? res.headers.getSetCookie() : [];
  for (const c of all) {
    const kv = c.split(";")[0];
    const i = kv.indexOf("=");
    if (i > 0) jar[kv.slice(0, i).trim()] = kv.slice(i + 1);
  }
  return jar["_m_h5_tk"] || null;
}

// offerId 하나의 상세 데이터
async function fetchOfferDetail(offerId, { cookie = "" } = {}) {
  const data = JSON.stringify({ offerId: String(offerId) });
  let jar = {}; // _m_h5_tk 등
  if (cookie) for (const p of cookie.split(/;\s*/)) { const i = p.indexOf("="); if (i>0) jar[p.slice(0,i)] = p.slice(i+1); }

  async function call(token) {
    const url = buildUrl(token, data);
    const cookieStr = Object.entries(jar).map(([k,v]) => `${k}=${v}`).join("; ");
    const res = await fetch(url, { headers: {
      "User-Agent": UA,
      "Referer": "https://detail.1688.com/",
      "Origin": "https://detail.1688.com",
      ...(cookieStr ? { Cookie: cookieStr } : {}),
    }});
    const mh5 = mergeSetCookies(res, jar);
    const text = await res.text();
    let json = null; try { json = JSON.parse(text); } catch {}
    return { json, text, mh5 };
  }

  // 1) 현재 토큰 (쿠키에 있으면 사용, 없으면 빈값→프라이밍 유도)
  let token = (jar["_m_h5_tk"] || "").split("_")[0];
  let r = await call(token);

  // 2) 토큰 비었으면 재시도 (set-cookie 로 받은 새 토큰)
  const ret0 = r.json?.ret?.[0] || "";
  if (/FAIL_SYS_TOKEN_EMPTY|FAIL_SYS_ILLEGAL_ACCESS|FAIL_SYS_TOKEN_EXOIRED|令牌为空/.test(ret0)) {
    token = (jar["_m_h5_tk"] || "").split("_")[0];
    if (token) r = await call(token);
  }

  const ret = r.json?.ret?.[0] || "(no ret)";
  return { ok: /SUCCESS/.test(ret), ret, data: r.json?.data || null, raw: r.json };
}

module.exports = { fetchOfferDetail };

// CLI: node detail-1688.js <offerId> [--cookie ...]
if (require.main === module) {
  (async () => {
    const offerId = process.argv[2];
    if (!offerId) { console.error("usage: node detail-1688.js <offerId>"); process.exit(1); }
    const r = await fetchOfferDetail(offerId);
    console.log("ret:", r.ret);
    console.log(JSON.stringify(r.data, null, 2).slice(0, 4000));
  })();
}
