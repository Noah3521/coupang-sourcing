# coupang-sourcing — CLI 사용법 & 의존성

Coupang 상품 소싱 데이터를 수집하는 CLI 레퍼런스입니다. 크게 두 갈래로 동작합니다.

- **수집(collection)** — (상품, 스토어) 쌍으로 가격·옵션·리뷰·소싱지표를 SQLite에 적재.
- **발굴(discovery)** — best100 랭킹 / 검색결과에서 잘 팔리는 상품을 찾아내고, 판매자를 해석해 위 수집으로 연결.

---

## 1. 의존성

### 필수 (Python)
| 항목 | 버전 | 비고 |
|---|---|---|
| Python | ≥ 3.10 | `tomllib`, `sqlite3` 등 표준 라이브러리 사용 |
| `curl_cffi` | ≥ 0.7 | Chrome TLS 임퍼스네이션(브라우저 없이 차단 우회) |
| `typer` | ≥ 0.12 | CLI 프레임워크 |
| `rich` | ≥ 13.0 | 표/컬러 출력 |

이 셋만 있으면 **대부분의 명령(best100 랭킹, 상품/배치 수집, refresh, export, schedule)은 브라우저·인증 없이** 동작합니다.

### Tier 2 전용 외부 의존성 (검색 / 판매자 해석에만 필요)
`search`, `mint-cookies`, 그리고 `--collect` 옵션은 Akamai로 보호된 경로를 쓰므로 **브라우저로 쿠키를 발급**해야 합니다.

| 항목 | 용도 | 경로 지정 |
|---|---|---|
| **Google Chrome** (또는 Chromium/Edge/Brave) | 헤드풀로 Akamai 센서를 풀어 쿠키 발급 | `COUPANG_CHROME=/path/to/chrome` |
| **Node.js** | CDP로 Chrome을 구동(쿠키 추출) | `COUPANG_NODE=/path/to/node` |

> 헤드리스 Chrome은 하드 차단됩니다 → **화면 있는(headful) Chrome 필수**. 서버/cron이면 가상 디스플레이가 필요합니다. 쿠키는 한 번 발급해 캐시(기본 1시간)에 재사용하므로, 브라우저는 매 요청이 아니라 **갱신 때만** 잠깐 뜹니다.

### 대시보드 전용 (선택)
Streamlit 시각화 대시보드는 `streamlit`, `pandas`가 필요합니다: `pip install -e ".[dashboard]"`.

### 개발
`pytest`, `ruff` (`pip install -e ".[dev]"`).

### 설치
```bash
cd ~/coupang-sourcing
uv venv && uv pip install -e ".[dev]"     # 또는: python -m venv .venv && pip install -e ".[dev]"
```

---

## 2. 명령 한눈에 보기

| 명령 | 용도 | 브라우저 | 인증 | 비고 |
|---|---|:---:|:---:|---|
| `init-db` | SQLite 스키마 생성 | ✗ | ✗ | |
| `product` | 상품 1개 풀수집 | ✗ | ✗ | (상품URL, 스토어URL) 필요 |
| `batch` | CSV로 다량 수집 | ✗ | ✗ | 스토어별 listing 1회 스캔 |
| `rank` | best100 랭킹 수집 | ✗* | ✗ | *`--collect` 시 ✓ |
| `rank-categories` | best100 카테고리 목록 | ✗ | ✗ | 드릴다운용 |
| `search` | 검색결과 수집(광고/일반 분리) | ✓ | ✗ | Akamai-gated |
| `mint-cookies` | Akamai 쿠키 강제 갱신 | ✓ | ✗ | |
| `refresh` | 기존 상품 재수집(시계열) | ✗ | ✗ | |
| `export` | 테이블 CSV/JSON 내보내기 | ✗ | ✗ | |
| `schedule` | 주기적 refresh 등록(launchd) | ✗ | ✗ | |
| `dashboard` | Streamlit 시각화 + UI에서 수집 | ✗* | ✗ | *수집 버튼이 gated면 Chrome |

> "브라우저 ✗"는 `curl_cffi`만으로 동작(대량 호출에도 안전), "✓"는 쿠키 발급용 Chrome이 필요함을 뜻합니다. **인증(로그인)은 어떤 명령도 요구하지 않습니다.**

---

## 3. 명령어 레퍼런스

### init-db
스키마 생성. 다른 명령도 필요 시 자동 생성하지만 명시적으로 만들 수 있습니다.
```bash
coupang-sourcing init-db --db sourcing.db
```

### product
상품 1개의 가격·메타·전체 리뷰·소싱지표를 수집. **상품 URL과 스토어 URL이 모두 필요**합니다(상품 URL만으로는 vendorId를 못 얻기 때문).
```bash
coupang-sourcing product \
  "https://www.coupang.com/vp/products/9042237424?itemId=26531314972&vendorItemId=93505444186" \
  "https://shop.coupang.com/A00333576" --db sourcing.db
```
주요 옵션: `--out DIR`(JSON/CSV도 덤프) · `--reviews/--no-reviews` · `--db-save/--no-db-save` · `--json`.

### batch
`product,store` 쌍 CSV를 한 번에 수집(스토어별 listing 1회만 스캔).
```bash
coupang-sourcing batch examples/batch_input.csv --db sourcing.db
```

### rank — best100 랭킹 (브라우저 불필요)
```bash
coupang-sourcing rank --board trending                       # 24시간 급상승
coupang-sourcing rank --board bestseller                     # 7일 판매량 베스트
coupang-sourcing rank --board bestseller --category 177195 --top 20
coupang-sourcing rank --board bestseller --category 177195 --collect   # 판매자 해석+풀수집
```
| 옵션 | 기본 | 설명 |
|---|---|---|
| `--board` | `bestseller` | `trending` \| `bestseller` |
| `--category` | `all` | `all` 또는 categoryId (모든 깊이 단일 처리) |
| `--top N` | `0` | 상위 N개만 (0=페이지 전체) |
| `--collect` | off | 판매자 해석 후 마켓셀러 상품 풀수집 (**브라우저 쿠키 필요**) |
| `--db-save/--no-db-save` | on | `rank_snapshots`에 적재 |
| `--json`, `-q` | | 기계용 출력 / 조용히 |

출력에 **"DB에 있음 N · 신규 후보 M"** 요약이 붙어 발굴 피드로 쓰입니다. 채널(판매유형)은 로켓/로켓프레시/로켓그로스/판매자배송으로 분류됩니다.

### rank-categories — 카테고리 탐색
```bash
coupang-sourcing rank-categories --board bestseller          # 대분류 9개 + 현재 페이지의 하위
coupang-sourcing rank-categories --category 177195           # 177195의 하위 카테고리
```
출력된 categoryId를 `rank --category <id>`에 넣어 드릴다운합니다.

### search — 검색결과 (Akamai-gated, 브라우저 쿠키 필요)
```bash
coupang-sourcing search 의자                                 # 첫 호출 시 Chrome 창으로 쿠키 발급
coupang-sourcing search 의자 --top 20 --json
coupang-sourcing search 의자 --collect                       # 판매자 해석 + 풀수집
```
| 옵션 | 기본 | 설명 |
|---|---|---|
| `--page N` | `1` | 결과 페이지 |
| `--top N` | `0` | 상위 N개만 |
| `--collect` | off | 판매자 해석 + 마켓셀러 풀수집 |
| `--db-save/--no-db-save` | on | `search_snapshots`에 적재 |

광고는 `sourceType=srp_product_ads`(+`광고` 라벨), 일반은 `sourceType=search`로 **분리 저장**(`is_ad` 플래그). 광고는 일반과 중복될 수 있어 rank로 위치를 보존합니다.

### mint-cookies — 쿠키 강제 갱신
```bash
coupang-sourcing mint-cookies
```
헤드풀 Chrome을 잠깐 띄워 Akamai 쿠키를 재발급하고 캐시에 저장합니다. (보통은 `search`/`--collect`가 만료 시 자동 갱신하므로 수동 실행은 선택사항.)

### refresh — 시계열 재수집
```bash
coupang-sourcing refresh --all
coupang-sourcing refresh --store A00333576 --older-than 7
```
기존 DB 상품을 다시 크롤해 가격/리뷰 스냅샷을 append. `--store` / `--all` / `--older-than N` 중 하나 필요.

### export — 내보내기
```bash
coupang-sourcing export --table products --format csv --out products.csv
coupang-sourcing export --table products --min-score 70 --store A00333576
coupang-sourcing export --table rank_snapshots --format csv --out rank.csv
coupang-sourcing export --table search_snapshots --format json --out search.json
```
허용 테이블: `products, reviews, product_snapshots, product_variants, stores, vendor_map, rank_snapshots, search_snapshots`. `products`는 `--store` / `--min-score` 필터 + 소싱점수 정렬.

### schedule — 주기 실행 (macOS launchd)
```bash
coupang-sourcing schedule install --interval daily --at 03:00 --all
coupang-sourcing schedule install --interval daily --dry-run   # plist 미리보기
coupang-sourcing schedule status
coupang-sourcing schedule uninstall
```
`hourly|daily|weekly`로 `refresh`를 등록. 비-macOS에선 `crontab` 라인을 출력합니다.

---

### dashboard
Streamlit 웹 대시보드로 **DB 시각화 + UI에서 직접 수집**.
```bash
pip install -e ".[dashboard]"                 # 최초 1회 (streamlit, pandas)
coupang-sourcing dashboard                     # 기본 DB(~/.coupang-sourcing/sourcing.db)
coupang-sourcing dashboard --db sourcing.db --port 8502
```
탭: **Overview**(소싱 후보 Top·테이블 카운트) · **Products**(필터·점수분포·가격↔평점 산점도) ·
**Trends**(상품별 가격/리뷰/랭크 시계열) · **Discovery**(best100 랭킹·검색 광고/일반 비율·DB보유 vs 신규) ·
**Sellers**(판매자별 집계). 왼쪽 **"➕ 수집"** 패널에서 `find_products`(best100/검색+필터+전체수집),
`product_info`(링크), `collect_seller`, 쿠키 갱신을 실행하면 같은 DB에 쌓이고 차트가 갱신됩니다. 검색/전체수집은
gated라 Chrome이 잠깐 뜰 수 있습니다.

## 4. 공통 옵션
대부분의 수집 명령에 적용:
`--db PATH`(SQLite 경로) · `--config PATH`(config.toml) · `--rate`(요청 간 기본 지연s) · `--timeout` · `--retries` · `--json`(기계용) · `-q/--quiet`. CLI 플래그가 config 값을 덮어씁니다.

---

## 5. 발굴 → 수집 연결 (`--collect`)
best100/검색 카드에는 productId·itemId·vendorItemId만 있고 **판매자(vendorId)는 없습니다.** `--collect`는:
1. 각 상품을 `vp/products/{pid}/vendoritems/{vid}` JSON(쿠키 필요)으로 조회 → `vendor.id`(=스토어 url-name) 해석.
2. 마켓셀러 상품을 기존 `(상품,스토어)` 흐름으로 **전체상품 풀수집**(`listing`은 쿠키 불필요·대량 안전).

해석은 **판매자당 1회**(캐시)라 부하가 작고, 무거운 전체수집은 쿠키 없는 안전 경로로 돌아갑니다. 단:
- best100은 약 80%가 **쿠팡 직매입**(마켓셀러 아님) → 전체수집 대상은 일부. 검색은 마켓셀러 비율이 더 높습니다.
- **브랜드스토어가 없는 판매자**는 `getStoreInfo`가 404 → 자동 스킵(한 판매자 실패가 배치를 멈추지 않음).

---

## 6. 데이터 모델 (SQLite)
| 테이블 | 내용 |
|---|---|
| `products` | 상품별 최신 스냅샷(가격/평점/채널/소싱점수) |
| `product_variants` | 정규화된 옵션 |
| `product_snapshots` | **시계열**: 크롤별 가격/리뷰수/평점 |
| `reviews` | 리뷰 본문(텍스트 마이닝용) |
| `stores`, `vendor_map` | 스토어 메타 + vendorName↔vendorId 캐시 |
| `rank_snapshots` | **시계열**: best100 랭킹(board/category/rank→product) |
| `search_snapshots` | **시계열**: 검색결과(query/rank, 광고/일반, 해석된 store) |

---

## 7. 설정 파일 (config.toml)
`config.example.toml` → `config.toml`(또는 `~/.config/coupang-sourcing/config.toml`). 주요 키:
`db_path, rate_delay, jitter, timeout, retries, retry_delay, review_size, max_review_pages, listing_max_pages, review_sort, sale_multiplier, complaint_keywords, scoring_weights`.

---

## 8. 쿠키 / 프로필 위치 (Tier 2)
| 경로 | 용도 |
|---|---|
| `~/.config/coupang-sourcing/cookies.json` | 발급된 Akamai 쿠키 캐시(기본 1시간 TTL, 만료/차단 시 자동 재발급) |
| `~/.config/coupang-sourcing/chrome-profile` | 쿠키 발급용 영속 Chrome 프로필(사람처럼 보이게 유지) |

---

## 9. 동작 원리 & 캐비엇
- **best100**(`/np/best100/*`)은 Akamai 정책이 느슨해 `curl_cffi`만으로 통과 → 대량 안전. 페이지당 SSR 랭킹 약 30개(스크롤 추가분은 JS라 제외).
- **검색**(`/np/search`)·**vendoritems**는 Akamai 인터스티셜로 보호 → 브라우저 발급 쿠키 필요. 쿠키는 `curl_cffi`로 replay해 빠르게 대량 조회.
- 차단은 **IP가 아니라 자동화 지문**(navigator.webdriver 등) 때문 — 발급 Chrome은 `--disable-blink-features=AutomationControlled` + 실제 GPU + 영속 프로필로 사람처럼 보이게 하고, **설치된 Chrome 버전에 맞춰 UA/JA3 임퍼스네이션을 정렬**합니다(불일치 시 간헐 챌린지).
- 카테고리 레벨에선 `trending`과 `bestseller`가 거의 겹칩니다(구분은 `--category all`에서 뚜렷).
- 어떤 명령도 **로그인/인증 토큰을 쓰지 않습니다.**
