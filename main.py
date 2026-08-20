import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

def sync_products_and_inventory():
    print("1. 오즈라나 서버에서 상품 및 재고 데이터 수집 중...")
    headers = {"X-Token": OZLANA_TOKEN}
    res = requests.get("http://www.ozlanacms.com.au:30008/products", headers=headers)
    
    if res.status_code != 200:
        print(f"오즈라나 데이터 수집 실패: {res.status_code}")
        return

    raw_data = res.json().get("data", "[]")
    products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    print(f"-> 총 {len(products)}개 상품 데이터 확인 완료")

    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    # 전체 상품 순회 (또는 테스트를 원하시면 products[:10] 처럼 설정 가능)
    for prod in products:
        prod_name = prod.get("prodName", "OZLANA Product")
        sku = prod.get("prodMark", "")
        # 오즈라나 API 데이터 구조에 따른 재고 수량 추출 (필드명 확인 필요)
        stock_qty = prod.get("stock", prod.get("quantity", 0))

        product_data = {
            "product": {
                "title": prod_name,
                "body_html": f"<strong>Model:</strong> {sku}<br><strong>Color:</strong> {prod.get('colorName')}",
                "vendor": "OZLANA",
                "variants": [
                    {
                        "sku": sku,
                        "price": "100.00",
                        "inventory_management": "shopify", # 쇼피파이가 재고 추적하도록 설정
                        "inventory_quantity": int(stock_qty) # 재고 수량 동기화
                    }
                ]
            }
        }
        
        url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
        response = requests.post(url, headers=shopify_headers, json=product_data)
        
        if response.status_code in [200, 201]:
            print(f"-> 동기화 성공: {prod_name} (재고: {stock_qty}개)")
        else:
            print(f"-> 실패({prod_name}): {response.status_code}")

if __name__ == "__main__":
    sync_products_and_inventory()
