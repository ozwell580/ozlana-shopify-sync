"""
Shopify에 등록된 'AS UGG' 벤더 상품들의 Description에서
오즈웨어 사이즈 가이드 링크를 에버어그 사이즈 가이드 링크로 교체합니다.

main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.
"""

import time

import requests

from main import get_shopify_access_token, SHOPIFY_STORE

OLD_URL = "https://ugg-aus.myshopify.com/pages/ozwear-size-guide-chart"
NEW_URL = "https://ugg-aus.myshopify.com/pages/everugg-size-guide"
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


def update_description(shopify_headers, store_domain, product_id, new_body_html):
    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}.json"
    payload = {"product": {"id": product_id, "body_html": new_body_html}}
    res = requests.put(url, headers=shopify_headers, json=payload)
    return res.status_code == 200


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

    updated = 0
    skipped_no_match = 0
    failed = 0

    for p in products:
        product_id = p.get("id")
        title = p.get("title", "")
        body_html = p.get("body_html", "") or ""

        if OLD_URL not in body_html:
            skipped_no_match += 1
            continue

        new_body_html = body_html.replace(OLD_URL, NEW_URL)

        if update_description(shopify_headers, store_domain, product_id, new_body_html):
            updated += 1
            print(f"[수정됨] {title} ({product_id})")
        else:
            failed += 1
            print(f"[실패] {title} ({product_id})")

        time.sleep(0.3)

    print(f"\n완료: 수정 {updated}개 / 해당없음(이미 정상) {skipped_no_match}개 / 실패 {failed}개")


if __name__ == "__main__":
    main()
