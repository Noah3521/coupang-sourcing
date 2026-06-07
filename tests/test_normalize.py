from coupang_sourcing.normalize import (
    is_overseas_like,
    normalize_product,
    parse_price,
    parse_review_payload,
    public_review_row,
)


def test_parse_price():
    assert parse_price("25,790원") == 25790
    assert parse_price(None) is None
    assert parse_price("없음") is None


def test_normalize_product_core_fields(raw_product):
    p = normalize_product(raw_product, "A00333576", 29119)
    assert p["productId"] == 9042237424
    assert p["price"] == 25790
    assert p["originalPrice"] == 27150
    assert p["discountRate"] == 5
    assert p["reviewCount"] == 503
    assert p["rocket"] is True
    assert p["image"].startswith("https://")


def test_overseas_like_false_for_rocket(raw_product):
    p = normalize_product(raw_product, "A00333576", 29119)
    assert is_overseas_like(p) is False


def test_overseas_like_true_for_slow_nonrocket():
    p = {"rocket": False, "deliveryText": "6/8 도착 예정", "outboundShippingPlaceId": 123}
    assert is_overseas_like(p) is True


def test_parse_review_payload(review_payload):
    parsed = parse_review_payload(review_payload)
    assert parsed["ok"] is True
    assert parsed["totalCount"] == 503
    assert parsed["totalPage"] == 17
    assert len(parsed["reviews"]) == 2


def test_public_review_row_flattens_attachments(review_payload):
    parsed = parse_review_payload(review_payload)
    row = public_review_row(parsed["reviews"][0], {"productId": 9042237424, "title": "t"})
    assert row["rating"] == 5
    assert row["attachmentCount"] == 1
    assert row["attachmentImages"].startswith("https://")
