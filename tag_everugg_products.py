"""
에버어그(AS UGG) 상품 중 특정 스타일 코드 목록에 해당하는 상품들에
구분용 태그(EVER-KIDS, EVER-ACC, EVER-BAG 등)를 추가합니다.

main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python tag_everugg_products.py --codes "AS8006,AS8007,..." --tag "EVER-BAG"
"""

import argparse
import re
import time

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
    variants = product.get("variants", [])
    if not variants:
        return None
    sku = str(variants[0].get("sku", "")).strip()
    m = re.match(r"AS-([A-Za-z0-9]+)-", sku, re.IGNORECASE)
    return m.group(1).upper() if m else None


def add_tag(shopify_headers, store_domain, product_id, existing_tags, new_tag):
    tags_set = {t.strip() for t in existing_tags.split(",") if t.strip()}
    if new_tag in tags_set:
        return True, "already_tagged"

    tags_set.add(new_tag)
    new_tags = ", ".join(sorted(tags_set))

    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}.json"
    payload = {"product": {"id": product_id, "tags": new_tags}}
    res = requests.put(url, headers=shopify_headers, json=payload)
    return res.status_code == 200, res.text if res.status_code != 200 else "ok"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", required=True, help="쉼표로 구분된 스타일 코드 목록")
    parser.add_argument("--tag", required=True, help="추가할 태그 이름")
    args = parser.parse_args()

    target_codes = {c.strip().upper() for c in args.codes.split(",") if c.strip()}
    print(f"대상 코드 {len(target_codes)}개, 태그: {args.tag}\n")

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

    tagged = 0
    already = 0
    not_matched_codes = set(target_codes)
    failed = 0

    for p in products:
        code = extract_code(p)
        if code not in target_codes:
            continue

        not_matched_codes.discard(code)

        ok, info = add_tag(
            shopify_headers, store_domain, p.get("id"), p.get("tags", ""), args.tag
        )
        if ok and info == "already_tagged":
            already += 1
        elif ok:
            tagged += 1
            print(f"[태그 추가] {p.get('title')} ({code})")
        else:
            failed += 1
            print(f"[실패] {p.get('title')} ({code}) - {info}")

        time.sleep(0.3)

    print(f"\n완료: 새로 태그 추가 {tagged}개 / 이미 있음 {already}개 / 실패 {failed}개")
    if not_matched_codes:
        print(f"Shopify에서 못 찾은 코드({len(not_matched_codes)}개): {sorted(not_matched_codes)}")


if __name__ == "__main__":
    main()
