"""
Shopify 'OZWEAR UGG' 벤더 상품 중 이미지가 없는 상품을 찾고,
그 스타일 코드가 오즈웨어 API에 지금도 존재하는지(단종 여부) 확인합니다.
"""

import re
import requests

from sync_ozwear_inventory import (
    get_shopify_access_token,
    OZWEAR_BASE_URL,
    SHOPIFY_STORE,
)

TARGET_VENDOR = "OZWEAR UGG"


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
    """Tags 필드에서 스타일 코드를 가져옵니다."""
    tags = product.get("tags", "")
    if tags:
        first_tag = tags.split(",")[0].strip()
        if first_tag:
            return first_tag.upper()
    return None


def get_ozwear_token():
    resp = requests.post(
        f"{OZWEAR_BASE_URL}/token",
        json={
            "key": __import__("os").environ.get("OZWEAR_API_KEY"),
            "secret": __import__("os").environ.get("OZWEAR_API_SECRET"),
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errorCode") not in (0, "0", None):
        raise RuntimeError(f"오즈웨어 토큰 발급 실패: {payload}")
    return payload["data"]["token"]


def check_code_exists_in_ozwear(token, code):
    headers = {"api_key": token, "Content-Type": "application/json"}
    resp = requests.post(
        f"{OZWEAR_BASE_URL}/products",
        headers=headers,
        json={"code": code, "page": 1, "pageSize": 5},
        timeout=30,
    )
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    payload = resp.json()
    if payload.get("errorCode") not in (0, "0", None):
        return None, str(payload)
    items = payload.get("data", {}).get("list", [])
    return len(items) > 0, f"{len(items)}개 항목"


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

    print(f"'{TARGET_VENDOR}' 상품 조회 중...")
    products = get_products_by_vendor(shopify_headers, store_domain, TARGET_VENDOR)
    print(f"-> {len(products)}개 상품 조회 완료\n")

    no_image_products = []
    for p in products:
        images = p.get("images", [])
        if len(images) == 0:
            code = extract_code(p)
            no_image_products.append((p.get("title", ""), code))

    print(f"이미지 없는 상품: {len(no_image_products)}개\n")

    ozwear_token = get_ozwear_token()

    still_active = []
    discontinued = []

    for title, code in no_image_products:
        if not code:
            print(f"[코드 추출 실패] {title}")
            continue

        exists, info = check_code_exists_in_ozwear(ozwear_token, code)
        if exists:
            still_active.append((title, code))
            print(f"[API에 있음 - 확인필요] {title} ({code}) - {info}")
        else:
            discontinued.append((title, code))
            print(f"[API에 없음 - 단종추정] {title} ({code}) - {info}")

    print(f"\n=== 요약 ===")
    print(f"API에 여전히 있는데 이미지 없는 상품 ({len(still_active)}개): 이미지 작업 누락 가능성")
    for title, code in still_active:
        print(f"  - {title} ({code})")

    print(f"\nAPI에 없는 상품 ({len(discontinued)}개): 단종 추정")
    for title, code in discontinued:
        print(f"  - {title} ({code})")


if __name__ == "__main__":
    main()
