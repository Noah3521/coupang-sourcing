import csv
import json

from coupang_sourcing import exporters, storage
from coupang_sourcing.models import ProductRecord


def _seed(db):
    storage.init_db(db)
    rec = ProductRecord(
        product={"productId": 1, "vendorItemId": 11, "itemId": 21, "title": "A",
                 "price": 1000, "originalPrice": 1200, "discountRate": 17, "link": "http://x/1"},
        variants=[{"vendorItemId": 11, "title": "A", "price": 1000, "soldOut": False,
                   "deliveryText": "", "image": ""}],
        store={"storeId": 9, "vendorId": "A00000001", "storeName": "S", "urlName": "A00000001"},
        reviews={"reviews": [{"reviewId": 100, "rating": 5, "title": "t", "content": "c",
                              "itemName": "A", "reviewAt": 1, "helpfulCount": 0}]},
        metrics={"ratingAverage": 4.5, "ratingCount": 10, "channel": "rocket", "sourcingScore": 88.0},
    )
    storage.save_record(db, rec)


def test_export_products_csv(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    out = tmp_path / "p.csv"
    path, count = exporters.export_table(db, "products", "csv", out)
    assert count == 1
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    assert rows[0]["product_id"] == "1"
    assert rows[0]["sourcing_score"] == "88.0"
    assert rows[0]["store"] == "A00000001"


def test_export_reviews_json(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    out = tmp_path / "r.json"
    path, count = exporters.export_table(db, "reviews", "json", out)
    assert count == 1
    data = json.loads(open(path, encoding="utf-8").read())
    assert data[0]["review_id"] == "100"


def test_export_rejects_unknown_table(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    try:
        exporters.export_table(db, "secrets; DROP TABLE products", "csv", tmp_path / "x.csv")
    except ValueError:
        return
    raise AssertionError("expected ValueError for non-whitelisted table")


def test_export_min_score_filter(tmp_path):
    db = tmp_path / "t.db"
    _seed(db)
    _, count = exporters.export_table(db, "products", "csv", tmp_path / "f.csv", min_score=99.0)
    assert count == 0
