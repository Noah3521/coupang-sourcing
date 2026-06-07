import pytest

from coupang_sourcing.urls import absolute_url, parse_product, parse_store, review_url


def test_parse_store_from_shop_url():
    assert parse_store("https://shop.coupang.com/A00333576?source=brandstore_sdp_atf") == "A00333576"


def test_parse_store_from_vid_path():
    assert parse_store("https://shop.coupang.com/vid/A01413843") == "A01413843"


def test_parse_store_plain_id():
    assert parse_store("A00333576") == "A00333576"


def test_parse_store_rejects_non_coupang():
    with pytest.raises(ValueError):
        parse_store("https://discord.com/channels/123/456/789")


def test_parse_product_full_url():
    ids = parse_product(
        "https://www.coupang.com/vp/products/9042237424?itemId=26531314972"
        "&vendorItemId=93505444186&sourceType=srp_product_ads"
    )
    assert ids["productId"] == "9042237424"
    assert ids["itemId"] == "26531314972"
    assert ids["vendorItemId"] == "93505444186"
    assert ids["sourceType"] == "srp_product_ads"


def test_parse_product_plain_id():
    assert parse_product("9042237424")["productId"] == "9042237424"


def test_parse_product_rejects_non_product_url():
    with pytest.raises(ValueError):
        parse_product("https://www.coupang.com/np/search?q=x")


def test_absolute_url_variants():
    assert absolute_url("//img.x/a.jpg") == "https://img.x/a.jpg"
    assert absolute_url("/vp/products/1").startswith("https://www.coupang.com/")
    assert absolute_url("https://a/b") == "https://a/b"
    assert absolute_url(None) == ""


def test_review_url_uses_next_api():
    url = review_url(9042237424, page=2, size=30)
    assert "/next-api/review?" in url
    assert "productId=9042237424" in url
    assert "page=2" in url
    assert "size=30" in url
