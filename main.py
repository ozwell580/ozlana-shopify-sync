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

def get_existing_shopify_products(shopify_headers):
    """쇼피파이 상품 및 Variant / InventoryItem ID 매핑"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250"
    response = requests.get(url, headers=shopify_headers)
    existing_map = {}
    
    if response.status_code == 200:
        products = response.json().get("products", [])
        for p in products:
            title = p["title"].strip()
            variants_map = {}
            for v in p.get("variants", []):
                if v.get("sku"):
                    variants_map[v.get("sku")] = {
                        "variant_id": v.get("id"),
                        "inventory_item_id": v.get("inventory_item_id")
                    }
            existing_map[title] = {
                "product_id": p["id"],
                "variants": variants_map
            }
    return existing_map

def sync_data():
    headers = {"X-Token": OZLANA_TOKEN}
    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    print("1. 쇼피파이 Location ID 확인 중...")
    location_id = get_shopify_location_id(shopify_headers)
    if not location_id:
        print("쇼피파이 Location ID를 불러오지 못했습니다.")
        return
    print(f"-> Location ID 확인 완료: {location_id}")

    print("2. 오즈라나 /stocks API 수집 중...")
    res_stocks = requests.get(f"{BASE_URL}/stocks", headers=headers)
    if res_stocks.status_code != 200:
        print(f"오즈라나 연동 실패: {res_stocks.status_code}")
        return

    raw_data = res_stocks.json().get("data", [])
    products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    print(f"-> 총 {len(products)}개 상품 데이터 수집 완료")

    print("3. 쇼피파이 기존 상품 데이터 매핑 중...")
    existing_products = get_existing_shopify_products(shopify_headers)

    for prod in products:
        prod_id = prod.get("id")
        prod_name = prod.get("prodName", "").strip()
        sku_prefix = prod.get("prodMark", "")
        color_name = prod.get("colorName", "")
        
        if not prod_name:
            continue

        trade_price = float(prod.get("prodTradePrice") or 0)
        final_price = f"{round(trade_price * MARGIN_RATE, 2):.2f}" if trade_price > 0 else "0.00"
        image_url = f"{BASE_URL}/image/{prod_id}" if prod_id else None
        images = [{"src": image_url}] if image_url else []
        stock_list = prod.get("stocks", [])

        # 기존 상품이 존재하는 경우
        if prod_name in existing_products:
            prod_info = existing_products[prod_name]
            existing_variants = prod_info["variants"]

            for s in stock_list:
                size_remark = s.get("sizeRemark", "Free")
                stock_num = int(s.get("stockNum", 0))
                sku = f"{sku_prefix}-{size_remark}"

                if sku in existing_variants:
                    v_info = existing_variants[sku]
                    variant_id = v_info["variant_id"]
                    inv_item_id = v_info["inventory_item_id"]

                    # 가격 업데이트
                    update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/variants/{variant_id}.json"
                    requests.put(update_url, headers=shopify_headers, json={"variant": {"id": variant_id, "price": final_price}})

                    # 재고 수량(Available) Location 지정 업데이트
                    if inv_item_id:
                        set_shopify_inventory(inv_item_id, location_id, stock_num, shopify_headers)

            print(f"-> [재고/가격 완벽 업데이트] {prod_name} ({sku_prefix})")

        # 신규 상품 등록
        else:
            variants = []
            if stock_list:
                for s in stock_list:
                    size_remark = s.get("sizeRemark", "Free")
                    barcode = str(s.get("barCode", ""))

                    variants.append({
                        "option1": size_remark,
                        "price": final_price,
                        "sku": f"{sku_prefix}-{size_remark}",
                        "barcode": barcode,
                        "inventory_management": "shopify"
                    })

            create_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
            product_data = {
                "product": {
                    "title": prod_name,
                    "body_html": f"<strong>Model:</strong> {sku_prefix}<br><strong>Color:</strong> {color_name}",
                    "vendor": "OZLANA",
                    "options": [{"name": "Size"}],
                    "images": images,
                    "variants": variants
                }
            }
            res = requests.post(create_url, headers=shopify_headers, json=product_data)
            
            # 신규 등록 후 각 옵션의 Inventory Location 수량 지정
            if res.status_code in [200, 201]:
                new_prod = res.json().get("product", {})
                new_variants = new_prod.get("variants", [])
                
                for nv in new_variants:
                    nv_sku = nv.get("sku", "")
                    inv_item_id = nv.get("inventory_item_id")
                    
                    # 해당 SKU의 오즈라나 재고 수량 찾기
                    target_stock = 0
                    for s in stock_list:
                        if f"{sku_prefix}-{s.get('sizeRemark', 'Free')}" == nv_sku:
                            target_stock = int(s.get("stockNum", 0))
                            break
                    
                    if inv_item_id:
                        set_shopify_inventory(inv_item_id, location_id, target_stock, shopify_headers)

                print(f"-> [신규 등록 및 재고 세팅 완료] {prod_name} ({sku_prefix})")

if __name__ == "__main__":
    sync_data()
