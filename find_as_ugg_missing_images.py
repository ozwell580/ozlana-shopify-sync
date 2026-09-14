"""
Shopify에서 'AS UGG' 벤더 상품 중 이미지(Media)가 하나도 없는 상품을 찾아,
그 스타일 코드 목록을 출력합니다.

main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.
"""

import re

import requests

from main import get_shopify_access_token, SHOPIFY_STORE

TARGET_VENDOR = "AS UGG"


def get_products_by_vendor(shopify_headers, store_domain, vendor):
    url = (
        f"https://{store_domain}/admin/api/2024-01/products.json"
        f"?limit=250&vendor={requests.utils.quote(vendor)}"
    )
    products = []

    while url:
        res = requests.get(url, headers=shopify_headers)
        if res.status_code != 200:
            print(f"[상품 조회 에러] {res.status_code} - {res.text}")
            break

        products.extend(res.json().get("products", []))

        link_header = res.headers.get("Link")
        url = None
        if link_header:
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link.split(";")[0].strip("<> ")

    return products


def extract_code(product):
    """상품의 첫 variant SKU에서 스타일 코드를 뽑습니다 (AS-{code}-... 형식)."""
    variants = product.get("variants", [])
    if not variants:
        return None
    sku = str(variants[0].get("sku", "")).strip()
    m = re.match(r"AS-([A-Za-z0-9]+)-", sku, re.IGNORECASE)
    return m.group(1).upper() if m else None


def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")

    products = get_products_by_vendor(shopify_headers, store_domain, TARGET_VENDOR)
    print(f"'{TARGET_VENDOR}' 벤더 상품 {len(products)}개 조회 완료\n")

    missing_codes = []

    for p in products:
        images = p.get("images", [])
        if len(images) == 0:
            code = extract_code(p)
            title = p.get("title", "")
            if code:
                missing_codes.append(code)
                print(f"[이미지 없음] {title} -> {code}")
            else:
                print(f"[이미지 없음, 코드 추출 실패] {title} ({p.get('id')})")

    unique_codes = sorted(set(missing_codes))
    print(f"\n총 이미지 없는 상품: {len(missing_codes)}개")
    print(f"고유 스타일 코드: {len(unique_codes)}개")
    print(",".join(unique_codes))


if __name__ == "__main__":
    main()
