from coupang_sourcing import storage
from coupang_sourcing.models import ProductRecord


def _record():
    return ProductRecord(
        product={"productId": 9042237424, "vendorItemId": 93505444186, "itemId": 26531314972,
                 "title": "화분", "price": 25790, "originalPrice": 27150, "discountRate": 5,
                 "link": "https://www.coupang.com/vp/products/9042237424"},
        variants=[{"vendorItemId": 93505444186, "title": "화분 A", "price": 25790,
                   "soldOut": False, "deliveryText": "", "image": ""}],
        store={"storeId": 29119, "vendorId": "A00333576", "storeName": "한가득마켓", "urlName": "A00333576"},
        reviews={"ratingSummary": {}, "reviews": [
            {"reviewId": 1, "rating": 5, "title": "t", "content": "c", "itemName": "A",
             "reviewAt": 1764716260000, "helpfulCount": 8, "attachments": [{"x": 1}]},
        ]},
        metrics={"ratingAverage": 4.5, "ratingCount": 503, "channel": "rocket", "sourcingScore": 77.0},
        is_ad=True,
    )


def test_init_and_upsert(tmp_path):
    db = tmp_path / "t.db"
    storage.init_db(db)
    storage.save_record(db, _record())
    counts = storage.table_counts(db)
    assert counts["products"] == 1
    assert counts["product_variants"] == 1
    assert counts["product_snapshots"] == 1
    assert counts["reviews"] == 1
    assert counts["vendor_map"] == 1


def test_snapshot_appends_but_product_dedupes(tmp_path):
    db = tmp_path / "t.db"
    storage.init_db(db)
    storage.save_record(db, _record())
    storage.save_record(db, _record())  # same product crawled again
    counts = storage.table_counts(db)
    assert counts["products"] == 1            # deduped by PK
    assert counts["product_snapshots"] == 2   # time series appended


def test_prior_snapshot_and_refresh_list(tmp_path):
    db = tmp_path / "t.db"
    storage.init_db(db)
    storage.save_record(db, _record())
    conn = storage.connect(db)
    prior = storage.get_prior_snapshot(conn, "9042237424")
    assert prior["review_total"] == 503
    targets = storage.list_products_for_refresh(conn, store="A00333576")
    assert len(targets) == 1
    assert targets[0]["product_id"] == "9042237424"
    conn.close()
