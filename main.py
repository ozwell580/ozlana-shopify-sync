import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

MARGIN_RATE = 1.21

def get_existing_shopify_products(shopify_headers):
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

    # [재고 필드명 확인용 로그 추가]
    if products:
        print("=== [오즈라나 데이터 전체 필드 확인] ===")
        print(json.dumps(products[0], indent=2, ensure_ascii=False))
        print("=========================================")

    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    existing_products = get_existing_shopify_products(shopify_headers)

    for prod in products:
        prod_name = prod.get("prodName", "OZLANA Product")
        sku = prod.get("prodMark", "")
        
        trade_price = float(prod.get("prodTradePrice") or 0)
        final_price = f"{round(trade_price * MARGIN_RATE, 2):.2f}" if trade_price > 0 else "0.00"
        
        # 오즈라나에 존재하는 여러 재고 가능성 필드 검색
        stock_qty = int(prod.get("stock") or prod.get("quantity") or prod.get("stockNum") or prod.get("prodStock") or prod.get("num") or 0)

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
                print(f"-> [업데이트] {prod_name} ({sku}) | 재고:{stock_qty}개 | 최종셀러가:${final_price}")

if __name__ == "__main__":
    sync_data()
