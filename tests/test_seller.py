from coupang_sourcing.collectors.seller import parse_vendor, vendoritems_url


def test_vendoritems_url():
    assert vendoritems_url("9442576019", "95044779503") == (
        "https://www.coupang.com/vp/products/9442576019/vendoritems/95044779503"
    )


def test_parse_vendor_marketplace():
    # Shape mirrors the real vendoritems JSON "vendor" object.
    payload = {"vendor": {"name": "주식회사 어몽두", "id": "A01388313",
                          "link": "https://shop.coupang.com/vid/A01388313?source=brandstore_sdp_atf"}}
    seller = parse_vendor(payload)
    assert seller == {
        "storeUrlName": "A01388313",
        "vendorName": "주식회사 어몽두",
        "link": "https://shop.coupang.com/vid/A01388313?source=brandstore_sdp_atf",
    }


def test_parse_vendor_coupang_direct_returns_none():
    # Coupang-direct (로켓 직매입) items carry no marketplace vendor id.
    assert parse_vendor({"vendor": {"name": "쿠팡", "id": None}}) is None
    assert parse_vendor({"vendor": {}}) is None
    assert parse_vendor({}) is None
