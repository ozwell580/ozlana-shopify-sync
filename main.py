import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

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

    # 쇼피파이 API 설정
    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    # 테스트로 오즈라나 상품 상위 5개를 쇼피파이에 등록합니다
    shopify_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
    
    for prod in products[:5]:
        product_data = {
            "product": {
                "title": prod.get("prodName", "OZLANA Product"),
                "body_html": f"<strong>Model:</strong> {prod.get('prodMark')}<br><strong>Color:</strong> {prod.get('colorName')}",
                "vendor": "OZLANA",
                "product_type": "Shoes",
                "variants": [
                    {
                        "option1": prod.get("colorName", "Default"),
                        "price": "100.00",
                        "sku": prod.get("prodMark", "")
                    }
                ]
            }
        }
        
        response = requests.post(shopify_url, headers=shopify_headers, json=product_data)
        if response.status_code == 201:
            print(f"-> 쇼피파이 등록 성공: {prod.get('prodName')}")
        else:
            print(f"-> 등록 실패({prod.get('prodName')}): {response.status_code} - {response.text}")

if __name__ == "__main__":
    sync_data()
