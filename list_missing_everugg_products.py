import os
import requests
from main import (
    get_shopify_access_token,
    get_existing_shopify_variants,
    fetch_everugg_stocks,
    build_everugg_sku_candidates,
)

def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    shopify_variants = get_existing_shopify_variants(shopify_headers)
    print(f"Shopify SKU {len(shopify_variants)}개 매핑 완료\n")

    everugg_data = fetch_everugg_stocks()
    print(f"EverUgg 데이터 {len(everugg_data)}건 수집 완료\n")

    missing_products = {}

    for item in everugg_data:
        candidates = build_everugg_sku_candidates(item)
        matched = any(c.upper() in shopify_variants for c in candidates)

        if not matched:
            code = str(item.get("ProductCode", "")).strip()
            name = str(item.get("ProductName", "")).strip()
            key = (code, name)
            missing_products.setdefault(key, 0)
            missing_products[key] += 1

    print(f"=== Shopify에 없는 상품 코드: {len(missing_products)}개 ===\n")
    for (code, name), count in sorted(missing_products.items()):
        print(f"{code} | {name} | 옵션 {count}개")

if __name__ == "__main__":
    main()
