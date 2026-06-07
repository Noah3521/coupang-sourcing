"""Pure transforms: raw Coupang API JSON -> normalized dicts.

Ported verbatim (behavior-preserving) from tools/coupang_shop_cli.py:
  parse_price 51, text_from_content 58, normalize_product 81, is_overseas_like 131,
  public_product_row 166, parse_review_payload 212, attachment_urls 229,
  video_urls 238, public_review_row 252, unique_products_by_product_id 285
"""
from __future__ import annotations

import re
from typing import Any

from .urls import absolute_url


def parse_price(value: Any) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return int(digits) if digits else None


def text_from_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list):
        return " ".join(part for part in (text_from_content(item) for item in value) if part)
    if isinstance(value, dict):
        keys = ("text", "title", "description", "content", "label", "value", "name")
        return " ".join(part for part in (text_from_content(value.get(key)) for key in keys) if part)
    return ""


def normalize_product(product: dict[str, Any], vendor_id: str, store_id: int | str) -> dict[str, Any]:
    title_area = product.get("imageAndTitleArea") or {}
    price_area = product.get("priceArea") or {}
    review_area = product.get("reviewArea") or {}
    btc_info = product.get("btcInfo") or {}
    promised_delivery = text_from_content((product.get("promisedDeliveryDateArea") or {}).get("contents"))
    delivery_badges = text_from_content((product.get("deliveryBadgeArea") or {}).get("badgeAreaContents"))
    top_badges = text_from_content(product.get("topBadgeAreas"))
    raw_link = product.get("link") or (
        f"/vp/products/{product.get('productId')}?itemId={product.get('itemId')}"
        f"&vendorItemId={product.get('vendorItemId')}&sourceType=brandstore"
        f"&vendorId={vendor_id}&storeId={store_id}"
    )
    detail_images = title_area.get("completeHttpDetailImageUrls") or title_area.get("detailImageUrls") or []
    return {
        "productId": product.get("productId"),
        "itemId": product.get("itemId"),
        "vendorItemId": product.get("vendorItemId"),
        "title": title_area.get("title") or "",
        "groupTitle": title_area.get("groupTitle") or "",
        "description": title_area.get("description") or "",
        "price": parse_price(price_area.get("salesPrice") or price_area.get("price")),
        "originalPrice": parse_price(price_area.get("originalPrice") or price_area.get("basePrice")),
        "discountRate": price_area.get("discountRate") or 0,
        "discount": bool(price_area.get("discount")),
        "instantDiscount": bool(price_area.get("instantDiscount")),
        "reviewCount": review_area.get("ratingCount") or 0,
        "ratingAverage": review_area.get("ratingAverage"),
        "ratingRatio": review_area.get("ratingRatio"),
        "rocket": bool((product.get("rocketArea") or {}).get("show") or btc_info.get("rocketDelivery")),
        "rocketMerchant": bool(product.get("rocketMerchant")),
        "coupangGlobal": bool(product.get("coupangGlobal")),
        "soldOut": bool((product.get("soldoutArea") or {}).get("soldout")),
        "valid": product.get("valid"),
        "adult": product.get("adult"),
        "deliveryText": " | ".join(part for part in (promised_delivery, delivery_badges, top_badges) if part),
        "cashbackText": (product.get("cashBackArea") or {}).get("cashRewardText") or "",
        "salesStartDate": product.get("salesStartDate") or "",
        "image": absolute_url(title_area.get("completeHttpUrl") or title_area.get("defaultUrl")),
        "detailImages": [absolute_url(url) for url in detail_images],
        "link": absolute_url(raw_link),
        "appLink": product.get("mlink") or "",
        "outboundShippingPlaceId": btc_info.get("outboundShippingPlaceId"),
        "batchShipment": btc_info.get("batchShipment"),
        "deliveryFee": btc_info.get("deliveryFee"),
        "freeShipOverAmountEx": btc_info.get("freeShipOverAmountEx"),
        "rawProductType": product.get("productType") or "",
    }


def is_overseas_like(product: dict[str, Any]) -> bool:
    delivery_text = product.get("deliveryText") or ""
    has_future_delivery_text = bool(re.search(r"\d{1,2}/\d{1,2}|도착 예정", delivery_text))
    has_remote_shipping_place = product.get("outboundShippingPlaceId") not in (None, 0, "0")
    return not product.get("rocket") and (has_future_delivery_text or has_remote_shipping_place)


def public_product_row(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "productId": product.get("productId"),
        "itemId": product.get("itemId"),
        "vendorItemId": product.get("vendorItemId"),
        "title": product.get("title"),
        "price": product.get("price"),
        "reviewCount": product.get("reviewCount"),
        "ratingAverage": product.get("ratingAverage"),
        "rocket": product.get("rocket"),
        "overseasLike": product.get("overseasLike"),
        "soldOut": product.get("soldOut"),
        "deliveryText": product.get("deliveryText"),
        "image": product.get("image"),
        "link": product.get("link"),
    }


def parse_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rdata = payload.get("rData") or {}
    paging = rdata.get("paging") or {}
    reviews = paging.get("contents") or []
    return {
        "ok": payload.get("rCode") == "RET0000",
        "rCode": payload.get("rCode"),
        "rMessage": payload.get("rMessage"),
        "ratingSummary": rdata.get("ratingSummaryTotal") or {},
        "totalCount": paging.get("totalCount") or rdata.get("reviewTotalCount") or 0,
        "totalPage": paging.get("totalPage") or 0,
        "currentPage": paging.get("currentPage") or paging.get("page"),
        "sizePerPage": paging.get("sizePerPage"),
        "reviews": reviews,
    }


def attachment_urls(review: dict[str, Any]) -> list[str]:
    urls = []
    for attachment in review.get("attachments") or []:
        url = (
            attachment.get("imgSrcOrigin")
            or attachment.get("imgSrcThumbnail")
            or attachment.get("uploadedFilePath")
        )
        if url:
            urls.append(absolute_url(url))
    return urls


def video_urls(review: dict[str, Any]) -> list[str]:
    urls = []
    for attachment in review.get("videoAttachments") or []:
        url = (
            attachment.get("videoUrl")
            or attachment.get("videoUrlOrigin")
            or attachment.get("videoSrc")
            or attachment.get("uploadedFilePath")
        )
        if url:
            urls.append(absolute_url(url))
    return urls


def public_review_row(review: dict[str, Any], source_product: dict[str, Any]) -> dict[str, Any]:
    images = attachment_urls(review)
    videos = video_urls(review)
    return {
        "sourceProductId": source_product.get("productId"),
        "sourceVendorItemId": source_product.get("vendorItemId"),
        "sourceTitle": source_product.get("title"),
        "sourceLink": source_product.get("link"),
        "reviewId": review.get("reviewId"),
        "productId": review.get("productId"),
        "itemId": review.get("itemId"),
        "vendorItemId": review.get("vendorItemId"),
        "rating": review.get("rating"),
        "title": review.get("title") or "",
        "content": review.get("content") or "",
        "itemName": review.get("itemName") or "",
        "itemImagePath": absolute_url(review.get("itemImagePath")),
        "displayName": review.get("displayName") or "",
        "displayWriter": review.get("displayWriter") or "",
        "vendorName": review.get("vendorName") or "",
        "reviewAt": review.get("reviewAt"),
        "createdAt": review.get("createdAt"),
        "helpfulCount": review.get("helpfulCount") or 0,
        "helpfulTrueCount": review.get("helpfulTrueCount") or 0,
        "helpfulFalseCount": review.get("helpfulFalseCount") or 0,
        "commentCount": review.get("commentCount") or 0,
        "attachmentCount": len(images),
        "attachmentImages": " | ".join(images),
        "videoCount": len(videos),
        "videoUrls": " | ".join(videos),
    }


def unique_products_by_product_id(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_product_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for product in products:
        product_id = product.get("productId")
        if product_id in (None, ""):
            continue
        key = str(product_id)
        if key not in by_product_id:
            by_product_id[key] = product
            order.append(key)
            continue
        current = by_product_id[key]
        if (product.get("reviewCount") or 0) > (current.get("reviewCount") or 0):
            by_product_id[key] = product
    return [by_product_id[key] for key in order]
