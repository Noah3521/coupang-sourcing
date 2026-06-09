#!/usr/bin/env bash
# aliprice-1688 sourcing :: installer (idempotent).
# Run from anywhere inside the repo:  bash integration/aliprice-1688/install.sh
# Does: npm install, download Chromium for Playwright, then print the cookie/usage steps.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
DB="${COUPANG_SOURCING_DB:-$HOME/.coupang-sourcing/sourcing.db}"

echo "==> dir: $SCRIPT_DIR"

# --- Node >= 22.5 (node:sqlite) ---
if ! command -v node >/dev/null 2>&1; then echo "ERROR: node not found (need >=22.5)"; exit 1; fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".") [0]')"
echo "==> node $(node -v)  (>=22.5 required; >=24 recommended)"

# --- deps ---
echo "==> npm install"
npm install --no-audit --no-fund

echo "==> playwright chromium"
npx --yes playwright install chromium

cat <<EOF

✅ installed.

NEXT:
  1) 로그인 세션 쿠키 추출 (Chrome 키체인 → 허용):
       node decrypt-cookies.js            # cookie.txt   (aiprice)
       node decrypt-cookies.js "%1688%"   # cookie.1688.txt (1688)
  2) 소싱 실행:
       node sourcing-pipeline.js          # 미소싱 쿠팡 상품 전체
       node sourcing-pipeline.js --product-id <id>   # 단일

DB: $DB
(자세한 옵션/스키마는 README.md 참고)
EOF
