import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

MARGIN_RATE = 1.21
BASE_URL = "http://www.ozlanacms.com.au:30008"

def get_shopify_location_id(shopify_headers):
    """쇼피파이 기본 Location ID 조회"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/locations.json"
    res = requests.get(url, headers=shopify_headers)
    if res.status_code == 200:
        locations = res.json().get("locations", [])
        if locations:
            return locations[0]["id"]
    return None

def set_shopify_inventory(inventory_item_id, location_id, quantity, shopify_headers):
    """location_id 기준으로 실제 재고 수량(Available) 세팅"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/inventory_levels/set.json"
    payload = {
        "location_id": location_id,
        "inventory_item_id": inventory_item_id,
        "available": quantity
    }
    requests.post(url, headers=shopify_headers, json=payload)

def get_existing_shopify_variants(shopify_headers):
    """쇼피파이 전체 Variant를 SKU 기준으로 매핑"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250"
    response = requests.get(url, headers=shopify_headers)
    sku_map = {}
    
    if response.status_code == 200:
        products = response.json().get("products", [])
        for p in products:
            for v in p.get("variants", []):
                sku = v.get("sku")
                if sku:
                    sku_map[sku.strip().upper()] = {
                        "variant_id": v.get("id"),
                        "inventory_item_id": v.get("inventory_item_id")
                    }
    return sku_map

def sync_data():
    headers = {"X-Token": OZLANA_TOKEN}
    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    print("1. 쇼피파이 Location ID 및 기존 Variant 수집 중...")
    location_id = get_shopify_location_id(shopify_headers)
    if not location_id:
        print("쇼피파이 Location ID를 불러오지 못했습니다.")
        return

    shopify_variants = get_existing_shopify_variants(shopify_headers)
    print(f"-> 총 {len(shopify_variants)}개 쇼피파이 SKU 매핑 완료")

    print("2. 오즈라나 /stocks API 수집 중...")
    res_stocks = requests.get(f"{BASE_URL}/stocks", headers=headers)
    if res_stocks.status_code != 200:
        print(f"오즈라나 연동 실패: {res_stocks.status_code}")
        return

    raw_data = res_stocks.json().get("data", [])
    products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data

    updated_count = 0

    for prod in products:
        sku_prefix = str(prod.get("prodMark", "")).strip().upper()
        color_name = str(prod.get("colorName", "")).strip().upper()
        
        trade_price = float(prod.get("prodTradePrice") or 0)
        final_price = f"{round(trade_price * MARGIN_RATE, 2):.2f}" if trade_price > 0 else "0.00"
        stock_list = prod.get("stocks", [])

        for s in stock_list:
            raw_size = str(s.get("sizeRemark", "")).strip()
            size_clean = raw_size.split("#")[0] if "#" in raw_size else raw_size
            stock_num = int(s.get("stockNum", 0))

            # 가능성 있는 다양한 SKU 대조 패턴
            possible_skus = [
                f"OZL-{sku_prefix}-{color_name}-{size_clean}",
                f"OZL-{sku_prefix}-{size_clean}",
                f"{sku_prefix}-{color_name}-{size_clean}",
                f"{sku_prefix}-{size_clean}"
            ]

            matched_variant = None
            for target_sku in possible_skus:
                if target_sku.upper() in shopify_variants:
                    matched_variant = shopify_variants[target_sku.upper()]
                    break

            if matched_variant:
                variant_id = matched_variant["variant_id"]
                inv_item_id = matched_variant["inventory_item_id"]

                # 1. 가격 업데이트
                update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/variants/{variant_id}.json"
                requests.put(update_url, headers=shopify_headers, json={"variant": {"id": variant_id, "price": final_price}})

                # 2. 재고 세팅 (Available)
                if inv_item_id:
                    set_shopify_inventory(inv_item_id, location_id, stock_num, shopify_headers)
                    updated_count += 1

    print(f"-> 총 {updated_count}개 옵션의 재고 및 가격 업데이트가 완벽하게 완료되었습니다!")

if __name__ == "__main__":
    sync_data()
