"""
오즈라나 쿠키 컬렉션 신상품 3개(OZ3035, OZ1041, OZ0033)를 Shopify에 신규 등록합니다.
가격 = VIP 공급가 * 1.1 (10% 마진), 사이즈는 5~9로 전개, SKU 형식은 OZL-{코드}-{색상}-{사이즈}.
이미지는 이 스크립트에서 넣지 않습니다(별도 스크립트에서 추가 예정).
main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python create_ozlana_cookie_products.py
"""

import requests

from main import get_shopify_access_token, SHOPIFY_STORE

SIZES = ["5", "6", "7", "8", "9"]

PRODUCTS = [
    {
        "code": "OZ3035",
        "name": "Cookie Mule Platform (Detachable Feature)",
        "colors": ["CHESTNUT", "SAND", "CHOCOLATE"],
        "material": "UPPER:COW SUEDE LINING:SHEEPSKIN INSOLE:SHEEPSKIN OUTSOLE:EVA",
        "weight_kg": 1.5,
        "heel_cm": 4,
        "vip_price": 50,
        "barcodes": {
            "CHESTNUT": {"5": "2630352945005", "6": "2630352945006", "7": "2630352945007", "8": "2630352945008", "9": "2630352945009"},
            "SAND": {"5": "2630352935005", "6": "2630352935006", "7": "2630352935007", "8": "2630352935008", "9": "2630352935009"},
            "CHOCOLATE": {"5": "2630352936005", "6": "2630352936006", "7": "2630352936007", "8": "2630352936008", "9": "2630352936009"},
        },
    },
    {
        "code": "OZ1041",
        "name": "Cookie Tazz (Detachable Feature)",
        "colors": ["CHESTNUT", "SAND", "CHOCOLATE"],
        "material": "UPPER:COW SUEDE LINING:SHEEPSKIN INSOLE:SHEEPSKIN OUTSOLE:EVA",
        "weight_kg": 1.5,
        "heel_cm": 4,
        "vip_price": 55,
        "barcodes": {
            "CHESTNUT": {"5": "2610412945005", "6": "2610412945006", "7": "2610412945007", "8": "2610412945008", "9": "2610412945009"},
            "SAND": {"5": "2610412946005", "6": "2610412946006", "7": "2610412946007", "8": "2610412946008", "9": "2610412946009"},
            "CHOCOLATE": {"5": "2610412947005", "6": "2610412947006", "7": "2610412947007", "8": "2610412947008", "9": "2610412947009"},
        },
    },
    {
        "code": "OZ0033",
        "name": "Cookie Mini Platform (Detachable Feature)",
        "colors": ["CHESTNUT", "SAND"],
        "material": "UPPER:COW SUEDE LINING:SHEEPSKIN INSOLE:SHEEPSKIN OUTSOLE:EVA",
        "weight_kg": 1.8,
        "heel_cm": 4,
        "vip_price": 54,
        "barcodes": {
            "CHESTNUT": {"5": "2600332945005", "6": "2600332945006", "7": "2600332945007", "8": "2600332945008", "9": "2600332945009"},
            "SAND": {"5": "2600332946005", "6": "2600332946006", "7": "2600332946007", "8": "2600332946008", "9": "2600332946009"},
        },
    },
]

MARGIN = 1.1


def build_product_payload(item):
    price = round(item["vip_price"] * MARGIN, 2)
    title = f"[{item['code']}] Ozlana {item['name']}"
    description = (
        f"소재: {item['material']}. "
        f"굽 높이: {item['heel_cm']}cm. "
        f"무게: {item['weight_kg']}kg."
    )

    variants = []
    for color in item["colors"]:
        for size in SIZES:
            barcode = item.get("barcodes", {}).get(color, {}).get(size)
            variants.append({
                "option1": color.title(),
                "option2": size,
                "price": str(price),
                "sku": f"OZL-{item['code']}-{color.upper()}-{size}",
                "barcode": barcode,
                "inventory_management": "shopify",
                "inventory_policy": "deny",
            })

    payload = {
        "product": {
            "title": title,
            "vendor": "Ozlana",
            "product_type": "Shoes",
            "body_html": f"<p>{description}</p>",
            "options": [
                {"name": "Color", "values": [c.title() for c in item["colors"]]},
                {"name": "Size", "values": SIZES},
            ],
            "variants": variants,
            "tags": "UGG, Shoes, Ozlana",
        }
    }
    return payload


def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    url = f"https://{store_domain}/admin/api/2024-01/products.json"

    for item in PRODUCTS:
        payload = build_product_payload(item)
        res = requests.post(url, headers=shopify_headers, json=payload)
        if res.status_code in (200, 201):
            product = res.json()["product"]
            print(f"[생성 완료] {item['code']} - {item['name']} (product_id: {product['id']}, 변형 {len(product['variants'])}개)")
        else:
            print(f"[실패] {item['code']} - {res.status_code} - {res.text}")


if __name__ == "__main__":
    main()
