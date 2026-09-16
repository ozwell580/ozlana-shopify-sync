"""
이미 Shopify에 등록된 오즈웨어(OZWEAR UGG) 상품들에, GitHub(ozwear_test.py)에 올려둔
images/{코드}/{색상}/*.jpg 이미지를 자동으로 연결합니다.
오즈웨어 상품은 Tags 필드의 첫 번째 값이 스타일 코드입니다.

ozlana-shopify-sync 저장소에 넣고 실행하세요 (main.py 등과 같은 위치).

사용법:
    python add_ozwear_images.py --codes "OZB057,OZB062,OZB063,OZB064,OZB065"
"""

import argparse
import os
import time

import requests

from sync_ozwear_inventory import get_shopify_access_token, SHOPIFY_STORE

GITHUB_USER = "ozwell580"
GITHUB_REPO = "ozwear_test.py"
GITHUB_BRANCH = "main"
IMAGES_DIR = "images"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

GITHUB_TOKEN = os.environ.get("IMAGES_REPO_TOKEN") or os.environ.get("GITHUB_TOKEN", "")


def _github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def github_raw_url(code, subfolder, filename):
    return (
        f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/{IMAGES_DIR}/{code}/{subfolder}/{filename}"
    )


def _github_list_dir(path):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}"
    res = requests.get(url, headers=_github_headers(), timeout=30)
    if res.status_code != 200:
        return []
    data = res.json()
    return data if isinstance(data, list) else []


def list_subfolders(code):
    result = {}
    entries = _github_list_dir(f"{IMAGES_DIR}/{code}")
    for entry in entries:
        if entry.get("type") != "dir":
            continue
        color = entry["name"]
        sub_entries = _github_list_dir(f"{IMAGES_DIR}/{code}/{color}")
        files = sorted(
            e["name"] for e in sub_entries
            if e.get("type") == "file" and e["name"].lower().endswith(IMAGE_EXTENSIONS)
        )
        if files:
            result[color] = files
        time.sleep(0.1)
    return result


def get_products_with_code(shopify_headers, store_domain, code):
    """Tags 필드에 code가 첫 태그로 들어있는 상품을 찾습니다."""
    url = f"https://{store_domain}/admin/api/2024-01/products.json?limit=250"
    matched_products = []

    while url:
        res = requests.get(url, headers=shopify_headers)
        if res.status_code != 200:
            print(f"[상품 조회 에러] {res.status_code} - {res.text}")
            break

        products = res.json().get("products", [])
        for p in products:
            tags = p.get("tags", "")
            first_tag = tags.split(",")[0].strip().upper() if tags else ""
            if first_tag == code.upper():
                matched_products.append({"product_id": p.get("id"), "title": p.get("title", "")})

        link_header = res.headers.get("Link")
        url = None
        if link_header:
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link.split(";")[0].strip("<> ")

    return matched_products


def upload_image(shopify_headers, store_domain, product_id, image_url, position=None):
    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}/images.json"
    payload = {"image": {"src": image_url}}
    if position:
        payload["image"]["position"] = position

    res = requests.post(url, headers=shopify_headers, json=payload)
    if res.status_code in (200, 201):
        return True
    print(f"  [이미지 업로드 실패] {res.status_code} - {res.text[:300]}")
    return False


def process_code(shopify_headers, store_domain, code):
    subfolders = list_subfolders(code)
    if not subfolders:
        print(f"[{code}] GitHub에 이미지 없음 - 건너뜀")
        return

    products = get_products_with_code(shopify_headers, store_domain, code)
    if not products:
        print(f"[{code}] Shopify에서 매칭되는 상품(Tags={code})을 못 찾음")
        return

    for product in products:
        product_id = product["product_id"]
        position = 1
        for folder_name, files in subfolders.items():
            for filename in files:
                image_url = github_raw_url(code, folder_name, filename)
                ok = upload_image(shopify_headers, store_domain, product_id, image_url, position=position)
                if ok:
                    print(f"[{code}] product {product_id} <- {folder_name}/{filename}")
                position += 1
                time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", required=True, help="쉼표로 구분된 스타일 코드 목록")
    args = parser.parse_args()

    codes = sorted({c.strip() for c in args.codes.split(",") if c.strip()})
    if not codes:
        print("처리할 코드가 없습니다.")
        return

    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")

    print(f"총 {len(codes)}개 코드 처리 시작\n")
    for code in codes:
        process_code(shopify_headers, store_domain, code)

    print("\n완료.")


if __name__ == "__main__":
    main()
