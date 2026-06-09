#!/usr/bin/env node
// aiprice-cli — 확장 없이 AiPrice 이미지검색 (확장이 쓰는 /Img/search_by_image 와 동일)
//
// 사용법:
//   node cli.js <이미지경로> [--provider 1688] [--page 1] [--size 20]
//   쿠키는 ./cookie.txt 또는 AIPRICE_COOKIE 환경변수에서 읽음 (로그인 세션 필요)
//   쿠키 안에 i_m_k / i_m_v (AES 키/IV) + PHPSESSID/token 등 로그인 쿠키가 있어야 함.
//
// 옵션으로 직접 키 지정: --key <i_m_k> --iv <i_m_v>
const fs = require("fs");
const path = require("path");
const { searchByImage, PROVIDERS } = require("./aiprice-web");

function parseArgs(argv) {
  const a = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t.startsWith("--")) { a[t.slice(2)] = (argv[i + 1] && !argv[i + 1].startsWith("--")) ? argv[++i] : true; }
    else a._.push(t);
  }
  return a;
}

// fetch 의 Cookie 헤더는 ByteString(latin1) 이어야 함 → 바이트범위 밖 값 가진 쿠키 제거
function sanitizeCookie(raw) {
  return raw.split(/;\s*/).filter(Boolean).filter(p => /^[\x20-\x7e]*$/.test(p)).join("; ");
}

function loadCookie(args) {
  let raw = "";
  if (args.cookie) raw = args.cookie;
  else if (process.env.AIPRICE_COOKIE) raw = process.env.AIPRICE_COOKIE;
  else {
    const f = path.join(__dirname, "cookie.txt");
    if (fs.existsSync(f)) raw = fs.readFileSync(f, "utf8").trim();
  }
  return sanitizeCookie(raw);
}

function cookieVal(cookie, name) {
  const m = cookie.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]+)"));
  return m ? decodeURIComponent(m[1]) : null;
}

(async () => {
  const args = parseArgs(process.argv.slice(2));
  const imgPath = args._[0];
  if (!imgPath) { console.error("이미지 경로를 지정하세요.\n예) node cli.js ./item.jpg --provider 1688"); process.exit(1); }

  const cookie = loadCookie(args);
  const key = args.key || cookieVal(cookie, "i_m_k");
  const iv  = args.iv  || cookieVal(cookie, "i_m_v");
  if (!key || !iv) {
    console.error("AES 키/IV가 없습니다. cookie.txt 에 i_m_k / i_m_v 를 포함하거나 --key/--iv 로 지정하세요.");
    process.exit(1);
  }

  const imageBase64 = fs.readFileSync(imgPath).toString("base64");
  const provider = args.provider || "1688";

  const r = await searchByImage({
    imageBase64, provider,
    page: Number(args.page || 1),
    pageSize: Number(args.size || 20),
    key, iv, cookie,
  });

  if (!r.json) { console.error("HTTP", r.status, r.text.slice(0, 300)); process.exit(2); }
  if (r.json.code !== 0) { console.error("API error:", JSON.stringify(r.json)); process.exit(3); }

  const data = r.json.data || [];
  console.log(`\n[${provider}] ${data.length} 건\n` + "=".repeat(60));
  for (const p of data) {
    console.log(`• ${p.title || ""}`.slice(0, 70));
    console.log(`  ₩/¥ ${p.price}  | 월판매 ${p.monthSold ?? "-"}  | ${p.real_url || p.url || ""}`);
  }
  console.log("=".repeat(60));
  if (args.json) console.log(JSON.stringify(r.json, null, 2));
})();
