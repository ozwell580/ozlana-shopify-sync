"""
오즈라나 쿠키 컬렉션 신상품 3개(OZ3035, OZ1041, OZ0033)의 색상 옵션 값을
"Sand" -> "Beige"로 변경합니다 (실제 사진 폴더명이 BEIGE였기 때문).
main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python fix_cookie_color_to_beige.py
"""

import requests

from main import get_shopify_access_token, SHOPIFY_STORE

PRODUCT_IDS = [8717754925241, 8717754990777, 8717755056313]


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

    for product_id in PRODUCT_IDS:
        url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}.json"
        res = requests.get(url, headers=shopify_headers)
        if res.status_code != 200:
            print(f"[조회 실패] product_id {product_id} - {res.text}")
            continue

        product = res.json()["product"]
        title = product.get("title")
        print(f"\n===== {title} (product_id: {product_id}) =====")

        changed = 0
        for v in product.get("variants", []):
            if (v.get("option1") or "").strip().lower() == "sand":
                variant_id = v["id"]
                update_url = f"https://{store_domain}/admin/api/2024-01/variants/{variant_id}.json"
                payload = {"variant": {"id": variant_id, "option1": "Beige"}}
                r = requests.put(update_url, headers=shopify_headers, json=payload)
                if r.status_code == 200:
                    changed += 1
                    print(f"[변경 완료] SKU: {v.get('sku')} -> Beige")
                else:
                    print(f"[변경 실패] SKU: {v.get('sku')} - {r.text}")

        # 상품 옵션 값 목록(options[].values)도 갱신 - Shopify는 보통 변형 변경 시 자동 반영되지만 확인차 재조회
        print(f"총 {changed}개 변형 색상 변경")


if __name__ == "__main__":
    main()
