import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

# 마진 비율 설정 (10% 마진 = 원가 x 1.10)
MARGIN_RATE = 1.10

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

    shopify_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"

    for prod in products:
        prod_name = prod.get("prodName", "OZLANA Product")
        sku = prod.get("prodMark", "")
        
        # 오즈라나 원가 수집 (price, wholesalePrice, cost 등 존재하는 원가 필드 확인)
        cost_price = float(prod.get("price") or prod.get("wholesalePrice") or prod.get("retailPrice") or 0)
        
        # 원가에 마진 10% 적용 및 소수점 둘째자리 반올림
        if cost_price > 0:
            final_price = f"{round(cost_price * MARGIN_RATE, 2):.2f}"
        else:
            final_price = "0.00"

        # 재고 수량 추출
        stock_qty = prod.get("stock", prod.get("quantity", 0))

        product_data = {
            "product": {
                "title": prod_name,
                "body_html": f"<strong>Model:</strong> {sku}<br><strong>Color:</strong> {prod.get('colorName', '')}",
                "vendor": "OZLANA",
                "variants": [
                    {
                        "sku": sku,
                        "price": final_price, # 마진 10% 적용된 최종 판매가
                        "inventory_management": "shopify",
                        "inventory_quantity": int(stock_qty)
                    }
                ]
            }
        }
        
        response = requests.post(shopify_url, headers=shopify_headers, json=product_data)
        if response.status_code in [200, 201]:
            print(f"-> 동기화 성공: {prod_name} | 오즈라나원가: ${cost_price} -> 최종판매가(10%마진): ${final_price}")
        else:
            print(f"-> 등록 실패({prod_name}): {response.status_code}")

if __name__ == "__main__":
    sync_data()
