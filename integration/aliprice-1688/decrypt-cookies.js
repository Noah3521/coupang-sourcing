#!/usr/bin/env node
// macOS Chrome 쿠키 복호화 → aiprice 로그인 쿠키 추출 → cookie.txt 생성
// 사용: node decrypt-cookies.js   (키체인 "Chrome Safe Storage" 접근 허용 팝업이 뜸 → 허용)
const { execSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const PROFILE = process.env.CHROME_PROFILE || "Default";
const COOKIES_DB = path.join(os.homedir(),
  "Library/Application Support/Google/Chrome", PROFILE, "Cookies");
const TMP_DB = "/tmp/aiprice_cookies.db";
const HOST_LIKE = process.argv[2] || "%aiprice%";

// 1) 키체인에서 Chrome Safe Storage 키 (← 여기서 허용 팝업)
const kcPass = execSync(
  `security find-generic-password -w -s "Chrome Safe Storage" -a "Chrome"`,
  { encoding: "utf8" }
).trim();

// 2) AES-128 키 유도 (macOS: PBKDF2-SHA1, salt=saltysalt, iter=1003, len=16)
const aesKey = crypto.pbkdf2Sync(kcPass, "saltysalt", 1003, 16, "sha1");

// 3) 쿠키 DB 복사 후 aiprice 쿠키 덤프 (host|name|X'hex')
fs.copyFileSync(COOKIES_DB, TMP_DB);
const rows = execSync(
  `sqlite3 "file:${TMP_DB}?mode=ro" "SELECT host_key||'|'||name||'|'||quote(encrypted_value) FROM cookies WHERE host_key LIKE '${HOST_LIKE}';"`,
  { encoding: "utf8" }
).trim().split("\n").filter(Boolean);

// 4) 복호화 (v10: AES-128-CBC, IV=16x0x20). 신버전 Chrome 은 평문 앞 32바이트 도메인 해시 prefix.
function decrypt(hex) {
  const buf = Buffer.from(hex.replace(/^X'|'$/g, ""), "hex");
  const ver = buf.slice(0, 3).toString();
  if (ver !== "v10") return buf.toString("utf8"); // 평문(미암호화)
  const iv = Buffer.alloc(16, 0x20);
  const dec = crypto.createDecipheriv("aes-128-cbc", aesKey, iv);
  dec.setAutoPadding(false);
  let out = Buffer.concat([dec.update(buf.slice(3)), dec.final()]);
  // PKCS7 패딩 제거
  const pad = out[out.length - 1];
  if (pad > 0 && pad <= 16) out = out.slice(0, out.length - pad);
  // 신버전: 앞 32바이트가 비출력 도메인 해시면 제거
  const s = out.toString("utf8");
  if (/[\x00-\x08\x0e-\x1f]/.test(s.slice(0, 32))) return out.slice(32).toString("utf8");
  return s;
}

const jar = {};
for (const r of rows) {
  const [host, name, hex] = r.split("|");
  try { jar[name] = decrypt(hex); } catch (e) { /* skip */ }
}

const cookieStr = Object.entries(jar).map(([k, v]) => `${k}=${v}`).join("; ");
fs.writeFileSync(path.join(__dirname, "cookie.txt"), cookieStr);
console.log(`✔ ${Object.keys(jar).length} cookies → cookie.txt`);
console.log("  keys:", Object.keys(jar).join(", "));
const must = ["PHPSESSID", "token", "i_m_k", "i_m_v"];
for (const m of must) console.log(`  ${m}: ${jar[m] ? "✔ " + String(jar[m]).slice(0, 16) + "…" : "�’ 없음"}`);
