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
    try:
        res = requests.get(url, headers=shopify_headers)
        if res.status_code == 200:
            locations = res.json().get("locations", [])
            if locations:
                return locations[0]["id"]
    except Exception as e:
        print(f"Location ID 조회 중 오류 발생: {e}")
    return None

def set_shopify_inventory(inventory_item_id, location_id, quantity, shopify_headers):
    """location_id 기준으로 실제 재고 수량(Available) 세팅"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/inventory_levels/set.json"
    payload = {
        "location_id": location_id,
        "inventory_item_id": inventory_item_id,
        "available": quantity
    }
    try:
        res = requests.post(url, headers=shopify_headers, json=payload)
        return res.status_code == 200
    except Exception as e:
        print(f"재고 세팅 실패 (Item ID: {inventory_item_id}): {e}")
        return False

def get_existing_shopify_variants(shopify_headers):
    """쇼피파이 전체 Variant를 SKU 기준으로 매핑"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250"
    sku_map = {}
    try:
        response = requests.get(url, headers=shopify_headers)
        if response.status_code == 200:
            products = response.json().get("products", [])
            for p in products:
                for v in p.get("variants", []):
                    sku = v.get("sku")
                    if sku:
                        sku_map[str(sku).strip().upper()] = {
                            "variant_id": v.get("id"),
                            "inventory_item_id": v.get("inventory_item_id")
                        }
    except Exception as e:
        print(f"쇼피파이 Variant 매핑 오류: {e}")
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
        print("Error: 쇼피파이 Location ID를 불러오지 못했습니다. API Token이나 Store 주소를 확인하세요.")
        return

    shopify_variants = get_existing_shopify_variants(shopify_headers)
    print(f"-> 총 {len(shopify_variants)}개 쇼피파이 SKU 매핑 완료")

    print("2. 오즈라나 /stocks API 수집 중...")
    try:
        res_stocks = requests.get(f"{BASE_URL}/stocks", headers=headers)
        if res_stocks.status_code != 200:
            print(f"오즈라나 연동 실패: 응답 코드 {res_stocks.status_code}")
            return

        res_json = res_stocks.json()
        raw_data = res_json.get("data", [])
        if isinstance(raw_data, str):
            products = json.loads(raw_data)
        elif isinstance(raw_data, list):
            products = raw_data
        else:
            print("알 수 없는 데이터 타입입니다.")
            return

    except Exception as e:
        print(f"오즈라나 데이터 파싱 오류: {e}")
        return

    updated_count = 0

    for prod in products:
        if not isinstance(prod, dict):
            continue

        raw_prod_mark = str(prod.get("prodMark", "")).strip().upper()
        # OZ30001 -> OZ0001 변환 처리
        converted_mark = raw_prod_mark.replace("OZ3", "OZ") if raw_prod_mark.startswith("OZ3") else raw_prod_mark
        
        color_name = str(prod.get("colorName", "")).strip().upper()
        
        try:
            trade_price = float(prod.get("prodTradePrice") or 0)
        except ValueError:
            trade_price = 0.0

        final_price = f"{round(trade_price * MARGIN_RATE, 2):.2f}" if trade_price > 0 else "0.00"
        stock_list = prod.get("stocks", [])
        if not isinstance(stock_list, list):
            continue

        for s in stock_list:
            if not isinstance(s, dict):
                continue

            raw_size = str(s.get("sizeRemark", "")).strip()
            size_clean = raw_size.split("#")[0] if "#" in raw_size else raw_size
            stock_num = int(s.get("stockNum", 0))

            # 매칭 가능한 모든 SKU 패턴 확장
            possible_skus = [
                f"OZL-{converted_mark}-{color_name}-{size_clean}",
                f"OZL-{raw_prod_mark}-{color_name}-{size_clean}",
                f"OZL-{converted_mark}-{size_clean}",
                f"OZL-{raw_prod_mark}-{size_clean}",
                f"{converted_mark}-{color_name}-{size_clean}",
                f"{raw_prod_mark}-{color_name}-{size_clean}"
            ]

            matched_variant = None
            for target_sku in possible_skus:
                if target_sku.upper() in shopify_variants:
                    matched_variant = shopify_variants[target_sku.upper()]
                    break

            if matched_variant:
                variant_id = matched_variant["variant_id"]
                inv_item_id = matched_variant["inventory_item_id"]

                # 1. 재고 관리 주체 설정(shopify) 및 가격 업데이트
                update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/variants/{variant_id}.json"
                update_payload = {
                    "variant": {
                        "id": variant_id,
                        "price": final_price,
                        "inventory_management": "shopify"
                    }
                }
                requests.put(update_url, headers=shopify_headers, json=update_payload)

                # 2. 재고 수량 세팅
                if inv_item_id:
                    if set_shopify_inventory(inv_item_id, location_id, stock_num, shopify_headers):
                        updated_count += 1

    print(f"-> 총 {updated_count}개 옵션의 재고 수량 세팅 완료!")

if __name__ == "__main__":
    sync_data()
