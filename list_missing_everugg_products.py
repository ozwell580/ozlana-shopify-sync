import os
from main import (
    get_shopify_access_token,
    get_existing_shopify_variants,
    get_everugg_token,
    fetch_everugg_stock_list,
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

    token = get_everugg_token()
    if not token:
        print("EverUgg 토큰 발급 실패")
        return

    sydrh_stock = fetch_everugg_stock_list("/Api/Stock/SydrhStock", token)
    print(f"SydrhStock(로즈힐) 데이터 {len(sydrh_stock)}건 수집 완료\n")

    missing_products = {}

    for item in sydrh_stock:
        product_code = str(item.get("ProductCode", "")).strip().upper()
        color_name = str(item.get("ColorName", "")).strip().upper()
        size = str(item.get("Size", "")).strip().upper()
        barcode = str(item.get("Barcode", "")).strip().upper()

        candidates = [
            f"AS-{product_code}-{color_name}-{size}",
            barcode,
        ]

        matched = any(c.upper() in shopify_variants for c in candidates if c)

        if not matched:
            name = str(item.get("ProductName", "")).strip()
            key = (product_code, name)
            missing_products.setdefault(key, 0)
            missing_products[key] += 1

    print(f"=== 로즈힐(SydrhStock)에만 있고 Shopify에 없는 상품 코드: {len(missing_products)}개 ===\n")
    for (code, name), count in sorted(missing_products.items()):
        print(f"{code} | {name} | 옵션 {count}개")

if __name__ == "__main__":
    main()
