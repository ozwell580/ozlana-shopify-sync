"""
Shopify에 이미 등록된 에버어그 상품(SKU가 'AS-'로 시작)들 중
이미지가 비어있는 상품을 찾아서:
  1) 에버어그 API에서 색상별 이미지를 가져와 채워 넣고
  2) 설명(Description) 끝에 사이즈 가이드 링크를 추가합니다.

상품을 새로 만들거나 지우지 않고, 기존 상품만 보강합니다.

준비물:
    pip install requests

환경변수 필요:
    SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET
    EVERUGG_USER_ID, EVERUGG_PASSWORD

실행:
    python add_everugg_images.py
"""

import os
import time

import requests

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET")

EVERUGG_BASE_URL = os.environ.get("EVERUGG_BASE_URL", "http://api.everugg.net.au:9990")
EVERUGG_USER_ID = os.environ.get("EVERUGG_USER_ID")
EVERUGG_PASSWORD = os.environ.get("EVERUGG_PASSWORD")

SIZE_GUIDE_URL = "https://ugg-aus.myshopify.com/pages/ozwear-size-guide-chart"
SIZE_GUIDE_HTML = f'<p><a href="{SIZE_GUIDE_URL}">사이즈 가이드 보기</a></p>'


# ---------- Shopify ----------

def get_shopify_access_token():
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    url = f"https://{store_domain}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }
    res = requests.post(url, json=payload, timeout=15)
    if res.status_code != 200:
        print(f"토큰 발급 실패 응답: {res.status_code} - {res.text}")
        return None
    return res.json().get("access_token")


def fetch_everugg_products(headers):
    """SKU가 'AS-'로 시작하고, 이미지가 없는 Shopify 상품 목록을 가져옵니다."""

    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    url = f"https://{store_domain}/admin/api/2024-01/products.json?limit=250"

    targets = []  # [{id, description, variants:[{sku, color}]}]

    while url:
        res = requests.get(url, headers=headers, timeout=30)
        res.raise_for_status()
        products = res.json().get("products", [])

        for p in products:
            variants = p.get("variants", [])
            skus = [v.get("sku", "") for v in variants]
            if not any(s.upper().startswith("AS-") for s in skus if s):
                continue
            if p.get("images"):
                continue  # 이미 이미지가 있으면 건너뜀

            parsed_variants = []
            for v in variants:
                sku = (v.get("sku") or "").strip().upper()
                parts = sku.split("-")
                if len(parts) >= 4 and parts[0] == "AS":
                    code = parts[1]
                    color = parts[2]
                    parsed_variants.append({"variant_id": v.get("id"), "code": code, "color": color})

            if parsed_variants:
                targets.append({
                    "id": p.get("id"),
                    "body_html": p.get("body_html") or "",
                    "variants": parsed_variants,
                })

        link_header = res.headers.get("Link")
        url = None
        if link_header:
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link.split(";")[0].strip("<> ")

    return targets


def add_product_image(headers, product_id, image_url, variant_ids=None):
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}/images.json"
    payload = {"image": {"src": image_url}}
    if variant_ids:
        payload["image"]["variant_ids"] = variant_ids
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    return res.status_code == 200


def update_product_description(headers, product_id, new_body_html):
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}.json"
    payload = {"product": {"id": product_id, "body_html": new_body_html}}
    res = requests.put(url, headers=headers, json=payload, timeout=30)
    return res.status_code == 200


# ---------- EverUgg ----------

def get_everugg_token():
    login_url = f"{EVERUGG_BASE_URL}/Api/Token/getToken"
    params = {"user": EVERUGG_USER_ID, "password": EVERUGG_PASSWORD}
    res = requests.get(login_url, params=params, timeout=10)
    res.raise_for_status()
    return res.json().get("result", {}).get("token")


def fetch_everugg_product_images(everugg_token, product_code):
    """해당 상품 코드의 색상별 이미지 URL을 {색상: 이미지URL} 형태로 돌려줍니다."""

    url = f"{EVERUGG_BASE_URL}/Api/Product/Product"
    params = {"token": everugg_token, "productNo": product_code}
    try:
        res = requests.get(url, params=params, timeout=20)
        if res.status_code != 200:
            return {}
        items = res.json().get("result", [])
        color_to_image = {}
        for item in items:
            color = str(item.get("ColorName", "")).strip().upper()
            images = item.get("ProductImage") or []
            if color and images and color not in color_to_image:
                color_to_image[color] = images[0]
        return color_to_image
    except Exception as e:
        print(f"  [{product_code}] 이미지 조회 실패: {e}")
        return {}


def main():
    if not all([SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET]):
        raise SystemExit("SHOPIFY_STORE / SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET 환경변수가 필요합니다.")
    if not all([EVERUGG_USER_ID, EVERUGG_PASSWORD]):
        raise SystemExit("EVERUGG_USER_ID / EVERUGG_PASSWORD 환경변수가 필요합니다.")

    access_token = get_shopify_access_token()
    if not access_token:
        raise SystemExit("Shopify 토큰 발급 실패")
    print("Shopify 토큰 발급 성공")

    shopify_headers = {"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}

    everugg_token = get_everugg_token()
    if not everugg_token:
        raise SystemExit("EverUgg 토큰 발급 실패")
    print("EverUgg 토큰 발급 성공")

    print("이미지가 없는 에버어그 상품 조회 중...")
    targets = fetch_everugg_products(shopify_headers)
    print(f"-> 대상 상품 {len(targets)}개 발견")

    image_cache = {}  # product_code -> {color: image_url}
    updated_count = 0
    no_image_count = 0

    for i, product in enumerate(targets, start=1):
        product_id = product["id"]
        codes_in_product = {v["code"] for v in product["variants"]}

        any_image_added = False

        for code in codes_in_product:
            if code not in image_cache:
                image_cache[code] = fetch_everugg_product_images(everugg_token, code)
                time.sleep(0.2)

            color_to_image = image_cache[code]

            for color, image_url in color_to_image.items():
                variant_ids = [
                    v["variant_id"] for v in product["variants"]
                    if v["code"] == code and v["color"] == color
                ]
                if add_product_image(shopify_headers, product_id, image_url, variant_ids or None):
                    any_image_added = True
                time.sleep(0.5)  # Shopify API 속도 제한 보호

        if any_image_added:
            updated_count += 1
        else:
            no_image_count += 1

        # 사이즈 가이드 링크가 설명에 없으면 추가
        if SIZE_GUIDE_URL not in product["body_html"]:
            new_body = f"{product['body_html']}{SIZE_GUIDE_HTML}"
            update_product_description(shopify_headers, product_id, new_body)
            time.sleep(0.5)

        if i % 20 == 0:
            print(f"진행: {i}/{len(targets)}")

    print("")
    print(f"완료: 이미지 추가된 상품 {updated_count}개, 이미지 못 찾은 상품 {no_image_count}개")


if __name__ == "__main__":
    main()
