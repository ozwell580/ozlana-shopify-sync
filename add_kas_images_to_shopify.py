"""
이미 Shopify에 등록된 에버어그(AS-*) 상품들에, GitHub에 올려둔
images/{코드}/{색상}/*.jpg 이미지를 자동으로 연결합니다.

- 색상별 대표 이미지 1장은 그 색상의 모든 Variant에 자동 연결됩니다
  (Shopify가 "이 색상 선택 시 이 사진으로 전환"을 인식하게 해줌).
- 같은 색상 폴더의 나머지 사진들은 상품 갤러리에 추가됩니다.

main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python add_kas_images_to_shopify.py --codes "AS2112M,AS2120,AS2126"

    또는 links CSV에 있는 모든 코드를 한번에:
    python add_kas_images_to_shopify.py --links-csv apparel_dropbox_links.csv
"""

import argparse
import csv
import sys
import time
from collections import defaultdict

import requests

from main import get_shopify_access_token, SHOPIFY_STORE

GITHUB_USER = "ozwell580"
GITHUB_REPO = "ozwear_test.py"
GITHUB_BRANCH = "main"
IMAGES_DIR = "images"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

_TREE_CACHE = None


def github_raw_url(code, subfolder, filename):
    return (
        f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/{IMAGES_DIR}/{code}/{subfolder}/{filename}"
    )


def _load_github_tree():
    """GitHub API로 ozwear_test.py 저장소의 전체 파일 목록을 한 번에 가져와 캐싱합니다.
    (로컬 파일시스템 대신 사용 - 어디서 실행하든 동작하도록)"""

    global _TREE_CACHE
    if _TREE_CACHE is not None:
        return _TREE_CACHE

    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/git/trees/{GITHUB_BRANCH}?recursive=1"
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    data = res.json()

    tree = defaultdict(lambda: defaultdict(list))  # tree[code][color] = [filenames]
    prefix = f"{IMAGES_DIR}/"
    for entry in data.get("tree", []):
        path = entry.get("path", "")
        if entry.get("type") != "blob" or not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split("/")
        if len(parts) != 3:
            continue
        code, color, filename = parts
        if filename.lower().endswith(IMAGE_EXTENSIONS):
            tree[code][color].append(filename)

    for code in tree:
        for color in tree[code]:
            tree[code][color].sort()

    _TREE_CACHE = tree
    print(f"GitHub 저장소 이미지 목록 로드 완료: 코드 {len(tree)}개")
    return tree


def list_local_subfolders(code):
    tree = _load_github_tree()
    return dict(tree.get(code, {}))


def get_products_with_code(shopify_headers, store_domain, code):
    """SKU가 AS-{code}-로 시작하는 variant를 가진 상품을 찾아서
    {product_id, variants: [{id, sku, color}]} 형태로 돌려줍니다."""

    prefix = f"AS-{code.upper()}-"
    url = f"https://{store_domain}/admin/api/2024-01/products.json?limit=250"
    matched_products = []

    while url:
        res = requests.get(url, headers=shopify_headers)
        if res.status_code != 200:
            print(f"[상품 조회 에러] {res.status_code} - {res.text}")
            break

        products = res.json().get("products", [])
        for p in products:
            variants = p.get("variants", [])
            code_variants = []
            for v in variants:
                sku = str(v.get("sku", "")).strip().upper()
                if sku.startswith(prefix):
                    parts = sku.split("-")
                    color = parts[2] if len(parts) > 2 else ""
                    code_variants.append({
                        "id": v.get("id"),
                        "sku": sku,
                        "color": color,
                    })
            if code_variants:
                matched_products.append({"product_id": p.get("id"), "variants": code_variants})

        link_header = res.headers.get("Link")
        url = None
        if link_header:
            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link.split(";")[0].strip("<> ")

    return matched_products


def upload_image(shopify_headers, store_domain, product_id, image_url, variant_ids=None, position=None):
    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}/images.json"
    payload = {"image": {"src": image_url}}
    if variant_ids:
        payload["image"]["variant_ids"] = variant_ids
    if position:
        payload["image"]["position"] = position

    res = requests.post(url, headers=shopify_headers, json=payload)
    if res.status_code in (200, 201):
        return True
    print(f"  [이미지 업로드 실패] {res.status_code} - {res.text[:300]}")
    return False


def process_code(shopify_headers, store_domain, code):
    subfolders = list_local_subfolders(code)
    if not subfolders:
        print(f"[{code}] 로컬 이미지 없음 - 건너뜀")
        return

    products = get_products_with_code(shopify_headers, store_domain, code)
    if not products:
        print(f"[{code}] Shopify에서 매칭되는 상품(SKU AS-{code}-*)을 못 찾음")
        return

    for product in products:
        product_id = product["product_id"]
        variants = product["variants"]

        # 색상별로 variant id 묶기
        color_to_variant_ids = {}
        for v in variants:
            color_to_variant_ids.setdefault(v["color"], []).append(v["id"])

        position = 1
        for folder_name, files in subfolders.items():
            variant_ids = None
            if folder_name.upper() in color_to_variant_ids:
                variant_ids = color_to_variant_ids[folder_name.upper()]
            elif folder_name == "_root":
                # 색상 구분 없는 폴더면 전체 variant에 대표 이미지로 연결
                all_ids = [vid for ids in color_to_variant_ids.values() for vid in ids]
                variant_ids = all_ids if len(color_to_variant_ids) == 1 else None

            for i, filename in enumerate(files):
                image_url = github_raw_url(code, folder_name, filename)
                # 폴더의 첫 사진만 variant에 연결(대표), 나머지는 갤러리용
                use_variant_ids = variant_ids if i == 0 else None
                ok = upload_image(
                    shopify_headers, store_domain, product_id, image_url,
                    variant_ids=use_variant_ids, position=position
                )
                if ok:
                    print(f"[{code}] product {product_id} <- {folder_name}/{filename} "
                          f"{'(variant 연결)' if use_variant_ids else '(갤러리)'}")
                position += 1
                time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", default="", help="쉼표로 구분된 스타일 코드 목록")
    parser.add_argument("--links-csv", default="", help="code,dropbox_folder_url 형식의 CSV (코드만 사용)")
    args = parser.parse_args()

    codes = []
    if args.codes:
        codes.extend(c.strip() for c in args.codes.split(",") if c.strip())
    if args.links_csv:
        with open(args.links_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            codes.extend(row["code"].strip() for row in reader if row.get("code", "").strip())

    codes = sorted(set(codes))
    if not codes:
        print("처리할 코드가 없습니다. --codes 또는 --links-csv를 지정하세요.")
        sys.exit(1)

    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        sys.exit(1)

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
