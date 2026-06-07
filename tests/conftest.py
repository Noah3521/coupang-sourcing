import pytest


@pytest.fixture
def raw_product():
    """Shape mirrors a real shop.coupang.com /api/v1/listing product row."""
    return {
        "productId": 9042237424,
        "itemId": 26531314972,
        "vendorItemId": 93505444186,
        "imageAndTitleArea": {
            "title": "한가득마켓 플라스틱화분 10개, 그린",
            "completeHttpUrl": "//img.coupangcdn.com/a.jpg",
        },
        "priceArea": {"salesPrice": "25,790", "originalPrice": "27,150", "discountRate": 5, "discount": True},
        "reviewArea": {"ratingCount": 503, "ratingAverage": 4.5},
        "rocketArea": {"show": True},
        "btcInfo": {"outboundShippingPlaceId": 0},
        "promisedDeliveryDateArea": {"contents": "내일(토) 도착 보장"},
    }


@pytest.fixture
def review_payload():
    """Shape mirrors a real www.coupang.com/next-api/review JSON payload."""
    return {
        "rCode": "RET0000",
        "rMessage": "",
        "rData": {
            "ratingSummaryTotal": {
                "ratingCount": 503,
                "ratingAverage": 4.5,
                "ratingSummaries": [
                    {"rating": 5, "count": 392, "percentage": 80},
                    {"rating": 1, "count": 7, "percentage": 1},
                ],
            },
            "paging": {
                "totalCount": 503,
                "totalPage": 17,
                "currentPage": 1,
                "sizePerPage": 30,
                "contents": [
                    {
                        "reviewId": 111, "productId": 9042237424, "rating": 5,
                        "title": "좋아요", "content": "튼튼하고 좋아요", "itemName": "옵션 A",
                        "displayName": "ssim", "vendorName": "판매자: 에이스 무역",
                        "reviewAt": 1764716260000, "helpfulCount": 8,
                        "attachments": [{"imgSrcOrigin": "//img/x.jpg"}],
                    },
                    {
                        "reviewId": 112, "productId": 9042237424, "rating": 2,
                        "title": "별로", "content": "배송이 느리고 파손됨", "itemName": "옵션 B",
                        "displayName": "kim", "reviewAt": 1764700000000, "helpfulCount": 1,
                    },
                ],
            },
        },
    }
