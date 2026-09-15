"""
main.py의 get_existing_shopify_variants()가 실제로 ASA068의 SKU를
정확히 가져오는지 확인합니다.
"""

from main import get_shopify_access_token, get_existing_shopify_variants

TARGET_SKU = "AS-ASA068-SADDLE-BROWN"

def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    shopify_variants = get_existing_shopify_variants(shopify_headers)
    print(f"총 {len(shopify_variants)}개 SKU 매핑 완료\n")

    if TARGET_SKU in shopify_variants:
        print(f"✅ '{TARGET_SKU}' 정확히 존재함: {shopify_variants[TARGET_SKU]}")
    else:
        print(f"❌ '{TARGET_SKU}' 없음")
        # 비슷한 SKU 찾기 (ASA068이 포함된 것들)
        similar = [k for k in shopify_variants.keys() if "ASA068" in k]
        print(f"'ASA068'이 포함된 SKU들: {similar}")

if __name__ == "__main__":
    main()
