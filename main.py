import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

# GST 10% x 셀러 마진 10% = 1.21 곱하기
MARGIN_RATE = 1.21
BASE_URL = "http://www.ozlanacms.com.au:30008"

def get_existing_shopify_products(shopify_headers):
    """쇼피파이에 기존 등록된 상품 및 Variant(사이즈) 정보 전체 조회 (중복 방지용)"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250"
    response = requests.get(url, headers=shopify_headers)
    existing_map = {}
    
    if response.status_code == 200:
        products = response.json().get("products", [])
        for p in products:
            title = p["title"].strip()
            existing_map[title] = {
                "product_id": p["id"],
                "variants": {v.get("sku"): v.get("id") for v in p.get("variants", []) if v.get("sku")}
            }
    return existing_map

def sync_data():
    headers = {"X-Token": OZLANA_TOKEN}
    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    print("1. 오즈라나 /stocks API 수집 중...")
    res_stocks = requests.get(f"{BASE_URL}/stocks", headers=headers)
    if res_stocks.status_code != 200:
        print(f"오즈라나 연동 실패: {res_stocks.status_code}")
        return

    raw_data = res_stocks.json().get("data", [])
    products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    print(f"-> 총 {len(products)}개 상품 데이터 수집 완료")

    print("2. 기존 쇼피파이 상품 데이터 매핑 중...")
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
        
        # --- [A] 기존 등록된 상품이 이미 존재하는 경우 (업데이트 처리) ---
        if prod_name in existing_products:
            prod_info = existing_products[prod_name]
            shopify_prod_id = prod_info["product_id"]
            existing_variants = prod_info["variants"]

            for s in stock_list:
                size_remark = s.get("sizeRemark", "Free")
                stock_num = int(s.get("stockNum", 0))
                sku = f"{sku_prefix}-{size_remark}"

                # 이미 쇼피파이에 존재하는 Variant(사이즈)면 수량과 가격만 업데이트
                if sku in existing_variants:
                    variant_id = existing_variants[sku]
                    update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/variants/{variant_id}.json"
                    v_data = {
                        "variant": {
                            "id": variant_id,
                            "price": final_price,
                            "inventory_management": "shopify",
                            "inventory_quantity": stock_num
                        }
                    }
                    requests.put(update_url, headers=shopify_headers, json=v_data)
            
            print(f"-> [중복 방지 & 업데이트 완료] {prod_name} ({sku_prefix})")

        # --- [B] 기존에 없는 신규 상품인 경우만 (생성 처리) ---
        else:
            variants = []
            if stock_list:
                for s in stock_list:
                    size_remark = s.get("sizeRemark", "Free")
                    stock_num = int(s.get("stockNum", 0))
                    barcode = str(s.get("barCode", ""))

                    variants.append({
                        "option1": size_remark,
                        "price": final_price,
                        "sku": f"{sku_prefix}-{size_remark}",
                        "barcode": barcode,
                        "inventory_management": "shopify",
                        "inventory_quantity": stock_num
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
            if res.status_code in [200, 201]:
                print(f"-> [신규 등록 완료] {prod_name} ({sku_prefix}) | 사이즈 {len(variants)}개 생성")

if __name__ == "__main__":
    sync_data()
