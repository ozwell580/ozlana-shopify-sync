"""
main.py의 실제 동기화 로직을 그대로 실행하면서, 지정한 코드들이
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

TARGET_CODES = ["AS7047K", "AS3172K", "AS2075K", "AS2063K", "AS3168K"]

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

    for target_code in TARGET_CODES:
        print(f"\n{'='*50}")
        print(f"코드: {target_code}")
        target_items = [item for item in everugg_data if str(item.get("ProductCode","")).strip().upper() == target_code]
        print(f"항목 수: {len(target_items)}")

        if not target_items:
            print(f"  -> EverUgg 데이터에 {target_code}가 없음!")
            similar = [k for k in shopify_variants.keys() if target_code in k]
            print(f"  '{target_code}'가 포함된 실제 Shopify SKU들: {similar}")
            continue

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
                print("매칭 실패! (해당 SKU가 Shopify에 없음)")
                similar = [k for k in shopify_variants.keys() if target_code in k]
                print(f"  '{target_code}'가 포함된 실제 Shopify SKU들: {similar}")

if __name__ == "__main__":
    main()
