"""
'cloths and bag' 시트 코드에 EVER-BAG 태그를 일괄로 붙이는 과정에서,
옷/아우터류(Type=Apparel)에도 EVER-BAG이 잘못 붙은 상품들이 있습니다.
이 스크립트는 Shopify의 Type(product_type) 필드를 기준으로:
  - Type이 Apparel인 상품 -> EVER-BAG 태그 제거
  - 그 외(진짜 가방류) -> EVER-BAG 태그 유지
main.py, tag_everugg_products.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python fix_ever_bag_tags.py
"""

import time

import requests

from tag_everugg_products import get_products_by_vendor, TARGET_VENDOR
from main import get_shopify_access_token, SHOPIFY_STORE

# Apparel로 취급할 Type 값들 (Shopify Product organization > Type 필드 기준)
APPAREL_TYPES = {"apparel"}


def remove_tag(shopify_headers, store_domain, product_id, existing_tags, tag_to_remove):
    tags_set = {t.strip() for t in existing_tags.split(",") if t.strip()}
    if tag_to_remove not in tags_set:
        return True, "not_present"

    tags_set.discard(tag_to_remove)
    new_tags = ", ".join(sorted(tags_set))

    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}.json"
    payload = {"product": {"id": product_id, "tags": new_tags}}
    res = requests.put(url, headers=shopify_headers, json=payload)
    return res.status_code == 200, res.text if res.status_code != 200 else "ok"


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

    products = get_products_by_vendor(shopify_headers, store_domain, TARGET_VENDOR)
    print(f"'{TARGET_VENDOR}' 벤더 상품 {len(products)}개 조회 완료\n")

    removed = 0
    kept = 0
    checked = 0

    for p in products:
        tags = p.get("tags", "")
        tags_set = {t.strip() for t in tags.split(",") if t.strip()}
        if "EVER-BAG" not in tags_set:
            continue

        checked += 1
        product_type = (p.get("product_type") or "").strip().lower()

        if product_type in APPAREL_TYPES:
            ok, info = remove_tag(
                shopify_headers, store_domain, p.get("id"), tags, "EVER-BAG"
            )
            if ok:
                removed += 1
                print(f"[EVER-BAG 제거] {p.get('title')} (Type: {p.get('product_type')})")
            else:
                print(f"[실패] {p.get('title')} - {info}")
            time.sleep(0.3)
        else:
            kept += 1
            print(f"[유지] {p.get('title')} (Type: {p.get('product_type')})")

    print(f"\n완료: EVER-BAG 붙어있던 상품 {checked}개 중 제거 {removed}개 / 유지 {kept}개")


if __name__ == "__main__":
    main()
