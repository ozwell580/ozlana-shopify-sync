import os
import requests
import json

OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

# GST 10% x 마진 10% = 1.21 곱하기
MARGIN_RATE = 1.21
BASE_URL = "http://www.ozlanacms.com.au:30008"

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

def get_ozlana_stocks(headers):
    """오즈라나 재고 API(/stocks) 호출"""
    res = requests.get(f"{BASE_URL}/stocks", headers=headers)
    stock_map = {}
    if res.status_code == 200:
        raw_data = res.json().get("data", "[]")
        stocks = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        for item in stocks:
            p_id = item.get("productId") or item.get("id") or item.get("prodId")
            qty = item.get("stock") or item.get("quantity") or item.get("num") or 0
            if p_id is not None:
                stock_map[str(p_id)] = int(qty)
    return stock_map

def sync_data():
    headers = {"X-Token": OZLANA_TOKEN}
    shopify_headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json"
    }

    print("1. 오즈라나 상품 및 재고 데이터 수집 중...")
    res_prod = requests.get(f"{BASE_URL}/products", headers=headers)
    if res_prod.status_code != 200:
        print(f"오즈라나 상품 연동 실패: {res_prod.status_code}")
        return

    raw_data = res_prod.json().get("data", "[]")
    products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    
    # 별도 재고 API 데이터 수집
    stock_map = get_ozlana_stocks(headers)
    print(f"-> 총 {len(products)}개 상품 및 재고 데이터 수집 완료")

    print("2. 기존 쇼피파이 등록 상품 조회 중...")
    existing_products = get_existing_shopify_products(shopify_headers)

    for prod in products:
        prod_id = prod.get("id")
        prod_name = prod.get("prodName", "OZLANA Product")
        sku = prod.get("prodMark", "")
        
        trade_price = float(prod.get("prodTradePrice") or 0)
        final_price = f"{round(trade_price * MARGIN_RATE, 2):.2f}" if trade_price > 0 else "0.00"
        
        # 재고 매핑 (없을 경우 기본 10개 설정)
        stock_qty = stock_map.get(str(prod_id), 10)

        # 이미지 엔드포인트 URL 생성 (/image/{product_id})
        image_url = f"{BASE_URL}/image/{prod_id}" if prod_id else None
        images = [{"src": image_url}] if image_url else []

        # 기존 상품 업데이트
        if sku in existing_products:
            prod_info = existing_products[sku]
            update_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/variants/{prod_info['variant_id']}.json"
            update_data = {
                "variant": {
                    "id": prod_info['variant_id'],
                    "price": final_price,
                    "inventory_management": "shopify",
                    "inventory_quantity": stock_qty
                }
            }
            res = requests.put(update_url, headers=shopify_headers, json=update_data)
            if res.status_code == 200:
                print(f"-> [업데이트 완료] {prod_name} ({sku}) | 가격:${final_price} | 재고:{stock_qty}개")
        
        # 신규 상품 등록 (사진 + 재고 포함)
        else:
            create_url = f"https://{SHOPIFY_STORE}/admin/api/2024-01/products.json"
            product_data = {
                "product": {
                    "title": prod_name,
                    "body_html": f"<strong>Model:</strong> {sku}<br><strong>Color:</strong> {prod.get('colorName', '')}",
                    "vendor": "OZLANA",
                    "images": images,
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
                print(f"-> [신규 등록 완료(사진포함)] {prod_name} ({sku}) | 가격:${final_price} | 재고:{stock_qty}개")

if __name__ == "__main__":
    sync_data()
