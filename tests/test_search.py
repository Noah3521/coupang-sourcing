from coupang_sourcing import storage
from coupang_sourcing.collectors.search import build_search_url, parse_search

# Mirrors real /np/search ProductUnit markup: href-with-sourceType, productName class,
# <del> original price + "23<!-- -->%" + sales <span>, star aria-label, split "(72)" count,
# and a 광고 span on the ad card.
SRP = """
<ul>
<li class="ProductUnit_productUnit__Qd6sv" data-id="2001">
  <a href="/vp/products/111?itemId=3001&amp;vendorItemId=2001&amp;sourceType=srp_product_ads">
    <img src="//thumbnail.coupangcdn.com/a.jpg">
    <div class="ProductUnit_productNameV2__cV9cw">의자 A</div>
    <div class="PriceArea_priceArea__NntJz">
      <del class="fw-line-through">112,500원</del>
      <div class="fw-font-bold">23<!-- -->%</div><div><span>86,000원</span></div>
    </div>
    <div class="ProductRating_productRating__jjf7W">
      <div aria-label="5" class="fw-inline-flex"><div class="ProductRating_fullRating__1t_jb"></div></div>
      <span>(</span><span>72</span><span>)</span>
    </div>
    <span>광고</span>
  </a>
</li>
<li class="ProductUnit_productUnit__Qd6sv" data-id="2002">
  <a href="/vp/products/222?itemId=3002&amp;vendorItemId=2002&amp;sourceType=search">
    <div class="ProductUnit_productNameV2__cV9cw">의자 B &amp; 책상</div>
    <div class="PriceArea_priceArea__NntJz"><div><span>38,900원</span></div></div>
    <div class="ProductRating_productRating__jjf7W">
      <div aria-label="4.5"></div><span>(</span><span>1,234</span><span>)</span>
    </div>
  </a>
</li>
<li class="ProductUnit_productUnit__Qd6sv" data-id="2003">
  <a href="/vp/products/333?itemId=3003&amp;vendorItemId=2003&amp;sourceType=search">
    <div class="ProductUnit_productNameV2__cV9cw">의자 C</div>
    <div class="PriceArea_priceArea__NntJz">
      <del>20,000원</del><div class="fw-font-bold">10<!-- -->%</div><div><span>18,000원</span></div>
    </div>
    <div class="ProductRating_productRating__jjf7W"><div aria-label="5"></div><span>(3)</span></div>
  </a>
</li>
</ul>
"""


def test_parse_search_organic_vs_ads():
    items = parse_search(SRP)
    assert [it["productId"] for it in items] == ["111", "222", "333"]
    assert [it["rank"] for it in items] == [1, 2, 3]
    assert [it["isAd"] for it in items] == [True, False, False]
    assert [it["sourceType"] for it in items] == ["srp_product_ads", "search", "search"]
    assert sum(1 for it in items if not it["isAd"]) == 2


def test_parse_search_fields_ad_card():
    ad = parse_search(SRP)[0]
    assert ad["itemId"] == "3001"
    assert ad["vendorItemId"] == "2001"
    assert ad["title"] == "의자 A"
    assert ad["price"] == 86000
    assert ad["originalPrice"] == 112500
    assert ad["discountRate"] == 23
    assert ad["ratingAverage"] == 5.0
    assert ad["reviewCount"] == 72
    assert ad["image"] == "https://thumbnail.coupangcdn.com/a.jpg"
    assert ad["link"].endswith("sourceType=srp_product_ads")


def test_parse_search_no_discount_and_entities():
    second = parse_search(SRP)[1]
    assert second["title"] == "의자 B & 책상"          # entity unescaped
    assert second["price"] == 38900
    assert second["originalPrice"] is None             # single price → no original
    assert second["discountRate"] == 0
    assert second["ratingAverage"] == 4.5
    assert second["reviewCount"] == 1234


def test_parse_search_empty():
    assert parse_search("<html><body>no results</body></html>") == []


def test_build_search_url():
    assert build_search_url("의자").startswith("https://www.coupang.com/np/search?")
    assert "channel=user" in build_search_url("의자")
    assert "page=2" in build_search_url("의자", page=2)
    assert "page=" not in build_search_url("의자", page=1)


def test_save_search_flags_ads_and_in_products(tmp_path):
    db = tmp_path / "t.db"
    storage.init_db(db)
    conn = storage.connect(db)
    conn.execute("INSERT INTO products(product_id, title, store_id) VALUES('222','existing',1)")
    conn.commit()
    conn.close()

    storage.save_search(db, "의자", parse_search(SRP))

    conn = storage.connect(db)
    rows = {r["product_id"]: (r["is_ad"], r["in_products"], r["source_type"])
            for r in conn.execute("SELECT product_id, is_ad, in_products, source_type FROM search_snapshots")}
    conn.close()
    assert rows["111"] == (1, 0, "srp_product_ads")   # ad, not in DB
    assert rows["222"] == (0, 1, "search")            # organic, already collected
    assert storage.table_counts(db)["search_snapshots"] == 3
