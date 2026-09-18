"""
쿠키 컬렉션 3개 상품의 이미지를 업로드 당시 position 순서를 기준으로 색상별로 구분해서,
각 색상의 대표 이미지(범위의 첫 번째 사진)를 해당 색상의 모든 Variant(사이즈별)에 연결합니다.
(업로드 시 Shopify가 원본 파일명의 폴더 경로(색상명)를 지워버려서, 업로드 당시 기록해둔
position 순서로 역추적하는 방식입니다)
main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python link_ozlana_cookie_variant_images.py
"""

import requests

from main import get_shopify_access_token, SHOPIFY_STORE

# position은 1부터 시작 (업로드 로그 기준), 범위는 [start, end] 양끝 포함
PRODUCTS = [
    {
        "code": "OZ3035",
        "product_id": 8717754925241,
        "color_ranges": {
            "Beige": (1, 7),
            "Chestnut": (8, 14),
            "Chocolate": (15, 21),
        },
    },
    {
        "code": "OZ1041",
        "product_id": 8717754990777,
        "color_ranges": {
            "Beige": (1, 7),
            "Chestnut": (8, 14),
            "Chocolate": (15, 21),
        },
    },
    {
        "code": "OZ0033",
        "product_id": 8717755056313,
        "color_ranges": {
            "Beige": (1, 7),
            "Chestnut": (8, 14),
        },
    },
]


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

    for item in PRODUCTS:
        product_id = item["product_id"]
        print(f"\n===== {item['code']} =====")

        # 상품 정보(변형 + 이미지) 조회
        url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}.json"
        res = requests.get(url, headers=shopify_headers)
        if res.status_code != 200:
            print(f"[조회 실패] {res.text}")
            continue
        product = res.json()["product"]

        images_by_position = {img["position"]: img["id"] for img in product.get("images", [])}

        # 색상별 대표 이미지 id (범위의 시작 position)
        representative_image = {}
        for color, (start, end) in item["color_ranges"].items():
            img_id = images_by_position.get(start)
            if img_id:
                representative_image[color] = img_id
                print(f"{color}: position {start} -> image_id {img_id}")
            else:
                print(f"[경고] {color} position {start}에 해당하는 이미지 못 찾음")

        # 변형에 이미지 연결
        for v in product.get("variants", []):
            color = (v.get("option1") or "").strip()
            image_id = representative_image.get(color)
            if not image_id:
                print(f"[건너뜀] SKU {v.get('sku')} - 색상 '{color}' 매칭 이미지 없음")
                continue

            variant_id = v["id"]
            update_url = f"https://{store_domain}/admin/api/2024-01/variants/{variant_id}.json"
            payload = {"variant": {"id": variant_id, "image_id": image_id}}
            r = requests.put(update_url, headers=shopify_headers, json=payload)
            if r.status_code == 200:
                print(f"[연결 완료] SKU {v.get('sku')} -> image_id {image_id}")
            else:
                print(f"[연결 실패] SKU {v.get('sku')} - {r.text}")


if __name__ == "__main__":
    main()
