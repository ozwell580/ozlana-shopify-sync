"""
main.py의 실제 동기화 로직을 그대로 실행하면서, ASA068 항목이
정확히 어느 단계에서 처리되는지(매칭/재고설정 성공여부) 추적합니다.
"""

from main import (
    get_shopify_access_token,
    get_shopify_location_id,
    get_existing_shopify_variants,
    fetch_everugg_stocks,
    build_everugg_sku_candidates,
    set_shopify_inventory,
    SHOPIFY_STORE,
)
import requests

def main():
    access_token = get_shopify_access_token()
    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    location_id = get_shopify_location_id(shopify_headers)
    print(f"Location ID: {location_id}")

    shopify_variants = get_existing_shopify_variants(shopify_headers)
    print(f"SKU 매핑 {len(shopify_variants)}개 완료")

    everugg_data = fetch_everugg_stocks()
    print(f"EverUgg 데이터 {len(everugg_data)}건 수집")

    target_items = [item for item in everugg_data if str(item.get("ProductCode","")).strip().upper() == "ASA068"]
    print(f"\nASA068 항목 수: {len(target_items)}")

    for item in target_items:
        print(f"\n항목: {item}")
        qty = int(item.get("AvaiStockQty", 0) or 0)
        candidates = build_everugg_sku_candidates(item)
        print(f"후보: {candidates}")

        matched_variant = None
        matched_sku = None
        for target_sku in candidates:
            if target_sku.upper() in shopify_variants:
                matched_variant = shopify_variants[target_sku.upper()]
                matched_sku = target_sku
                break

        if matched_variant:
            print(f"매칭됨! SKU={matched_sku}, variant={matched_variant}")
            inv_item_id = matched_variant["inventory_item_id"]
            print(f"재고 설정 시도: inventory_item_id={inv_item_id}, location_id={location_id}, qty={qty}")

            # set_shopify_inventory를 직접 호출하고 실제 응답까지 확인
            store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
            url = f"https://{store_domain}/admin/api/2024-01/inventory_levels/set.json"
            payload = {
                "location_id": location_id,
                "inventory_item_id": inv_item_id,
                "available": qty
            }
            res = requests.post(url, headers=shopify_headers, json=payload)
            print(f"API 응답 status: {res.status_code}")
            print(f"API 응답 내용: {res.text}")
        else:
            print("매칭 실패!")

if __name__ == "__main__":
    main()
