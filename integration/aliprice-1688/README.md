# AliPrice → 1688 Sourcing Integration

각 Coupang 상품의 **이미지로 1688 원가 후보(top-N)를 찾아** 메타데이터까지 수집해
coupang-sourcing의 SQLite DB(`products`)에 **자식으로 귀속 저장**하는 Node 통합 도구.

쿠팡 판매상품 ↔ 1688 원가/공급처를 매핑해 **소싱 마진 분석**에 쓴다.

```
Coupang 상품(product_variants.image)
   → AliPrice 이미지검색(1688)  → 상위 N개 오퍼
   → 상위 K개 헤드리스 풀스크랩(SKU·사양·계단가·갤러리) + 전체 mtop 상세(판매/가격 이력)
   → coupang-sourcing DB 에 정규화 저장 (s1688_* 테이블, FK = products.product_id)
```

## 요구 사항
- **macOS** + **Chrome**에 다음 두 계정 로그인 상태:
  - `aiprice.com` (이미지검색 세션) · `1688.com`/`taobao.com` (상세 조회 세션)
- **Node ≥ 22.5** (DB 드라이버 `node:sqlite` 내장). Node 24+ 권장(플래그 불필요), 22.5–23.x 는 `--experimental-sqlite` 필요.
- coupang-sourcing DB가 채워져 있어야 함(기본 `~/.coupang-sourcing/sourcing.db`).

## 설치
```bash
cd integration/aliprice-1688
bash install.sh          # npm install + chromium 다운로드 안내
# 또는 수동:
npm install
npx playwright install chromium
```

## 쿠키 추출 (1회 / 만료 시)
Chrome 키체인에서 로그인 세션 쿠키를 복호화해 로컬 파일로 저장한다. **쿠키 파일은 .gitignore 처리됨(비밀값).**
```bash
node decrypt-cookies.js              # → cookie.txt   (aiprice 세션: i_m_k/i_m_v/PHPSESSID/token)
node decrypt-cookies.js "%1688%"     # → cookie.1688.txt (1688 세션)
```
> 실행 시 macOS 키체인 접근 허용 팝업 → **항상 허용**. 자격증명은 어디에도 전송되지 않고 로컬에만 저장된다.

## 사용
```bash
# 미소싱 쿠팡 상품 전체 — 상위 10개 검색, 상위 3개만 풀 헤드리스
node sourcing-pipeline.js

# 단일 상품
node sourcing-pipeline.js --product-id 9571071986

# 옵션
node sourcing-pipeline.js \
  --db ~/.coupang-sourcing/sourcing.db \  # COUPANG_SOURCING_DB 환경변수도 가능
  --limit 20 \           # 처리 개수 제한
  --order score|recent \ # sourcing_score 순(기본) / 최근크롤 순
  --top 10 \             # 상품당 1688 오퍼 수
  --headless-top 3 \     # 헤드리스 풀스크랩 상위 K (0=끄기, --no-headless 동일)
  --resource \           # 이미 소싱된 상품도 재소싱(upsert)
  --delay 800            # 상품 간 지연(ms, 지터 포함)
```
**멱등성**: `status='ok'`인 상품은 다음 실행에서 자동 스킵(`--resource`로 재소싱). aiprice 쿠키 만료(응답 code≠0)면 런을 자동 중단하고 안내 → `decrypt-cookies.js` 재실행.

## 저장 스키마 (coupang-sourcing DB에 추가)
부모는 기존 `products(product_id)`. 자식은 `match_id = '<product_id>:<offer_id>'`로 묶인다.

| 테이블 | 내용 |
|---|---|
| `s1688_offers` | 오퍼 본체(스칼라): 가격(현재/환산/min/max)·월판매·30일/총판매·재구매율·호평율·카테고리·등록일·재고·MOQ·rank 등 |
| `s1688_shop` | 판매자 지표(별점·연차·응답율·이행율·슈퍼팩토리…) |
| `s1688_price_history` | 일별 가격이력(max/min·수량·거래수) |
| `s1688_sales_history` | 일별 판매량 |
| `s1688_sale_ranges` | 일별 가격대 |
| `s1688_price_ladder` | 계단식 수량가격(헤드리스) |
| `s1688_sku` | SKU 변형(색상/규격+이미지, 헤드리스) |
| `s1688_specs` | 사양표 key/value(헤드리스) |
| `s1688_gallery` | 이미지 갤러리(헤드리스) |
| `s1688_identities` | 판매자/오퍼 식별자 |
| `sourcing_runs` / `sourcing_product_status` | 런 추적·멱등성 |

### 조회 예 (소싱 마진)
```sql
SELECT c.title 쿠팡, c.latest_price 쿠팡가,
       o.rank, o.title 원가후보, o.price_cny, o.month_sold, sh.shop_name, sh.tpyear
FROM products c
JOIN s1688_offers o ON o.coupang_product_id = c.product_id
LEFT JOIN s1688_shop sh USING(match_id)
WHERE c.product_id = '7586492914'
ORDER BY o.rank;
```

## 부가 CLI (단독 사용)
```bash
node cli.js <image> --provider 1688|coupang|aliexpress|taobao_lite|domeggook  # 이미지검색만
node enrich-1688.js <image> --top 5 --headless-top 3 --out top5.json          # 단일 이미지 메타수집
node headless-1688.js <offerId>                                               # 단일 1688 상세 스크랩
```

## 동작 원리 / 주의
- AliPrice 이미지검색은 `POST aiprice.com/Img/search_by_image`(AES-GCM 서명, 키는 세션 쿠키 `i_m_k/i_m_v`)를 그대로 호출. 1688 상세는 `mtop.1688.pc.plugin.od.data.query`(토큰 프라이밍 내장). SKU/사양/계단가는 baxia 보호로 Playwright 렌더링으로 수집.
- **본인 로그인 세션**으로만 동작(자격증명 미내장). 과도한 호출은 차단·약관 위반 소지가 있으니 소량·개인 소싱 용도로.
- 프록시(WireGuard KR 로테이션)는 기본 OFF. 로그인 세션+데이터센터 IP는 risk-control을 오히려 유발할 수 있어 소규모에선 불필요.
