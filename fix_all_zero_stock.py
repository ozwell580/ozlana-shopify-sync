"""
Shopify AS UGG 상품 중 재고가 0인 것들을 전부 찾아서,
에버어그 API에 실제로 재고가 있는지 대조한 뒤, 있으면 즉시 수정합니다.

main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.
"""

import re
import requests

from main import (
    get_shopify_access_token,
    get_shopify_location_id,
    fetch_everugg_stocks,
    build_everugg_sku_candidates,
    SHOPIFY_STORE,
)

TARGET_VENDOR = "AS UGG"


def get_products_with_variants(shopify_headers, store_domain, vendor):
    url = (
        f"https://{store_domain}/admin/api/2024-01/products.json"
        f"?limit=250&vendor={requests.utils.quote(vendor)}"
    )
    products = []

    while url:
        res = requests.get(url, headers=shopify_headers)
        if res.status_code != 200:
            print(f"[상품 조회 에러] {res.status_code} - {res.text}")
            break

        products.extend(res.json().get("products", []))

        link_header = res.headers.get("Link")
        url = None
        if link_header:
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link.split(";")[0].strip("<> ")

    return products


def get_zero_stock_skus(products):
    """0으로 표시된 모든 SKU와 그 inventory_item_id를 모읍니다."""
    zero_stock = {}
    for p in products:
        for v in p.get("variants", []):
            sku = str(v.get("sku", "")).strip().upper()
            qty = v.get("inventory_quantity", 0)
            if sku and qty == 0:
                zero_stock[sku] = {
                    "inventory_item_id": v.get("inventory_item_id"),
                    "title": p.get("title", ""),
                }
    return zero_stock


def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")

    location_id = get_shopify_location_id(shopify_headers)
    print(f"Location ID: {location_id}")

    print(f"'{TARGET_VENDOR}' 상품 조회 중...")
    products = get_products_with_variants(shopify_headers, store_domain, TARGET_VENDOR)
    print(f"-> {len(products)}개 상품 조회 완료")

    zero_stock = get_zero_stock_skus(products)
    print(f"-> 재고 0인 SKU {len(zero_stock)}개 발견\n")

    print("EverUgg 재고 데이터 수집 중...")
    everugg_data = fetch_everugg_stocks()
    print(f"-> {len(everugg_data)}건 수집 완료\n")

    fixed_count = 0
    still_zero_correctly = 0
    fixed_list = []

    for item in everugg_data:
        qty = int(item.get("AvaiStockQty", 0) or 0)
        if qty <= 0:
            continue  # 실제로 재고가 없는 건 건너뜀

        candidates = build_everugg_sku_candidates(item)

        for candidate in candidates:
            candidate_upper = candidate.upper()
            if candidate_upper in zero_stock:
                info = zero_stock[candidate_upper]
                inv_item_id = info["inventory_item_id"]

                url = f"https://{store_domain}/admin/api/2024-01/inventory_levels/set.json"
                payload = {
                    "location_id": location_id,
                    "inventory_item_id": inv_item_id,
                    "available": qty
                }
                res = requests.post(url, headers=shopify_headers, json=payload)

                if res.status_code == 200:
                    fixed_count += 1
                    fixed_list.append(f"{info['title']} ({candidate}) -> {qty}개")
                    print(f"[수정됨] {info['title']} ({candidate}) -> {qty}개")

                del zero_stock[candidate_upper]  # 중복 처리 방지
                break

    print(f"\n완료: {fixed_count}개 상품 재고 수정함")
    if fixed_list:
        print("\n수정된 목록:")
        for line in fixed_list:
            print(f"  - {line}")

    print(f"\n여전히 0으로 남은 SKU 수: {len(zero_stock)}개 (실제로 재고가 없거나 EverUgg 데이터에 없는 것들)")


if __name__ == "__main__":
    main()
