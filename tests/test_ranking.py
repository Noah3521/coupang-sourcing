import pytest

from coupang_sourcing import storage
from coupang_sourcing.collectors.ranking import discover_categories, parse_ranking
from coupang_sourcing.urls import best100_url

# Mirrors real /np/best100 markup: href-before-class anchor, data-log-click viewType,
# data-src placeholder + real src, biz-badge ids, a sold-out card, and a bottom widget.
FIXTURE = """
<html><body>
<div class="category-nav">
  <a href="/np/best100/bestseller/176422" data-log-props='{"id":"x"}'>뷰티</a>
  <a href="/np/best100/bestseller/194176">식품</a>
  <a href="/np/best100/trending/all">실시간</a>
</div>
<ul class="best100">
<li class="search-product " id="111"
    data-vendor-item-id="2001" data-winner-vendor-item-id="2001" data-product-id="111">
  <a href="/vp/products/111?itemId=3001&amp;vendorItemId=2001&amp;sourceType=brandstore"
     class="search-product-link" target="_blank"
     data-log-click='{"viewType":"toprank_unit","productId":"111","itemId":"3001","vendorItemId":"2001"}'
     data-product-id="111" data-item-id="3001" data-vendor-item-id="2001">
  <dl><dt class="image">
   <img data-src="data:image/gif;base64,PLACEHOLDER" src="//thumbnail.coupangcdn.com/a.jpg" alt="A" />
  </dt><dd>
   <div class="name">테스트 의자 &amp; 책상, 1개</div>
   <div class="price-area"><div class="price"><em class="sale">
     <span class="price-value-box"><strong class="price-value">39,490</strong>원</span>
     <div class="biz-badge-box"><img data-badge-id="ROCKET"><img data-badge-id="TOMORROW"></div>
   </em></div></div>
   <div class="other-info"><div class="rating-star">
     <span class="star"><em class="rating" style="width:100%">5.0</em></span>
     <span class="rating-total-count">(23474)</span>
   </div></div>
  </dd></dl></a>
</li>
<li class="search-product soldout" id="222" data-vendor-item-id="2002" data-product-id="222">
  <a href="/vp/products/222?itemId=3002&amp;vendorItemId=2002" class="search-product-link"
     data-log-click='{"viewType":"toprank_unit","productId":"222","itemId":"3002","vendorItemId":"2002"}'>
   <div class="name">품절 상품</div>
   <strong class="price-value">9,600</strong>원
   <img data-badge-id="ROCKET_MERCHANT">
   <em class="rating" style="width:90%">4.5</em>
   <span class="rating-total-count">(15)</span>
  </a>
</li>
<li class="search-product " id="999" data-vendor-item-id="2099" data-product-id="999">
  <a href="/vp/products/999?itemId=3099&amp;vendorItemId=2099" class="search-product-link"
     data-log-click='{"viewType":"bottom_widget","productId":"999"}'>
   <div class="name">추천 위젯 상품</div>
   <strong class="price-value">1,000</strong>원
  </a>
</li>
</ul>
</body></html>
"""


def test_parse_ranking_fields():
    items = parse_ranking(FIXTURE)
    assert [it["productId"] for it in items] == ["111", "222"]  # widget (999) dropped
    assert [it["rank"] for it in items] == [1, 2]               # contiguous ranks
    first = items[0]
    assert first["itemId"] == "3001"
    assert first["vendorItemId"] == "2001"
    assert first["title"] == "테스트 의자 & 책상, 1개"          # entity unescaped
    assert first["price"] == 39490
    assert first["ratingAverage"] == 5.0
    assert first["reviewCount"] == 23474
    assert first["channel"] == "rocket"
    assert first["soldOut"] is False
    assert first["image"] == "https://thumbnail.coupangcdn.com/a.jpg"   # real src, not data: placeholder
    assert first["link"] == (
        "https://www.coupang.com/vp/products/111?itemId=3001&vendorItemId=2001&sourceType=brandstore"
    )


def test_parse_ranking_soldout_and_channel():
    second = parse_ranking(FIXTURE)[1]
    assert second["soldOut"] is True
    assert second["channel"] == "rocket_merchant"
    assert second["reviewCount"] == 15


def test_parse_ranking_drops_bottom_widget():
    assert all(it["productId"] != "999" for it in parse_ranking(FIXTURE))


def test_parse_ranking_empty():
    assert parse_ranking("<html><body>no products</body></html>") == []


def test_discover_categories():
    cats = discover_categories(FIXTURE)
    assert {"categoryId": "176422", "name": "뷰티"} in cats
    assert "194176" in [c["categoryId"] for c in cats]


def test_best100_url():
    assert best100_url("trending") == "https://www.coupang.com/np/best100/trending/all"
    assert best100_url("bestseller", "177195") == "https://www.coupang.com/np/best100/bestseller/177195"
    with pytest.raises(ValueError):
        best100_url("foo")
    with pytest.raises(ValueError):
        best100_url("trending", "not-a-number")


def test_save_ranking_marks_in_products(tmp_path):
    db = tmp_path / "t.db"
    storage.init_db(db)
    conn = storage.connect(db)
    conn.execute("INSERT INTO products(product_id, title, store_id) VALUES('111','existing',1)")
    conn.commit()
    conn.close()

    storage.save_ranking(db, "trending", "all", parse_ranking(FIXTURE))

    conn = storage.connect(db)
    rows = {r["product_id"]: r["in_products"]
            for r in conn.execute("SELECT product_id, in_products FROM rank_snapshots")}
    conn.close()
    assert rows == {"111": 1, "222": 0}          # known product flagged, new one not
    assert storage.table_counts(db)["rank_snapshots"] == 2


def test_save_ranking_appends_distinct_captures(tmp_path):
    db = tmp_path / "t.db"
    storage.init_db(db)
    items = parse_ranking(FIXTURE)
    storage.save_ranking(db, "trending", "all", items)
    storage.save_ranking(db, "bestseller", "176422", items)   # different PK space
    assert storage.table_counts(db)["rank_snapshots"] == 4
