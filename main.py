import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

# GST 10% (1.10) x 마진 10% (1.10) = 1.21 곱하기
MARGIN_RATE = 1.21

def get_existing_shopify_products(shopify_headers):
    """쇼피파이에 기존 등록된 상품 SKU 맵핑"""
    url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json?limit=250"
    response = requests.get(url, headers=shopify_headers)
    existing_map = {}
    
    if response.status_code == 200:
        products = response.json().get("products", [])
        for p in products:
            for variant in p.get("variants", []):
                sku = variant.get("sku")
                if sku:
                    existing_map[sku] = {
                        "product_id": p["id"],
                        "variant_id": variant["id"]
                    }
    return existing_map

def sync_data():
    print("1. 오즈라나 서버 데이터 수집 중...")
    headers = {"X-Token": OZLANA_TOKEN}
    res = requests.get("http://www.ozlanacms.com.au:30008/products", headers=headers)
    
    if res.status_code != 200:
        print(f"오즈라나 연동 실패: {res.status_code}")
        return

    raw_data = res.json().get("data", "[]")
    products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    print(f"-> 총 {len(products)}개 상품 수집 완료")

    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    print("2. 기존 쇼피파이 등록 상품 조회 중...")
    existing_products = get_existing_shopify_products(shopify_headers)

    for prod in products:
        prod_name = prod.get("prodName", "OZLANA Product")
        sku = prod.get("prodMark", "")
        
        # 오즈라나 도매가(Excl. GST) -> GST 10% 및 마진 10% 자동 계산 (1.21)
        trade_price = float(prod.get("prodTradePrice") or 0)
        final_price = f"{round(trade_price * MARGIN_RATE, 2):.2f}" if trade_price > 0 else "0.00"
        stock_qty = int(prod.get("stock", prod.get("quantity", 0)))

        # 기존 상품 업데이트 (가격, 재고)
        if sku in existing_products:
            prod_info = existing_products[sku]
            update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/variants/{prod_info['variant_id']}.json"
            update_data = {
                "variant": {
                    "id": prod_info['variant_id'],
                    "price": final_price,
                    "inventory_quantity": stock_qty
                }
            }
            res = requests.put(update_url, headers=shopify_headers, json=update_data)
            if res.status_code == 200:
                print(f"-> [업데이트] {prod_name} ({sku}) | 공급가:${trade_price} -> 최종셀러가(GST+마진):${final_price}")
        
        # 신규 상품 등록
        else:
            create_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
            product_data = {
                "product": {
                    "title": prod_name,
                    "body_html": f"<strong>Model:</strong> {sku}<br><strong>Color:</strong> {prod.get('colorName', '')}",
                    "vendor": "OZLANA",
                    "variants": [{
                        "sku": sku,
                        "price": final_price,
                        "inventory_management": "shopify",
                        "inventory_quantity": stock_qty
                    }]
                }
            }
            res = requests.post(create_url, headers=shopify_headers, json=product_data)
            if res.status_code in [200, 201]:
                print(f"-> [신규등록] {prod_name} ({sku}) | 공급가:${trade_price} -> 최종셀러가(GST+마진):${final_price}")

if __name__ == "__main__":
    sync_data()
