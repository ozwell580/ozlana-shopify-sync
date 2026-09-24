"""
OZWEAR 상품 가격 일괄 +10% 조정 스크립트 (일회성)
==================================================
지금 Shopify에 등록된 OZWEAR(vendor: "OZWEAR UGG") 상품의 모든 variant 가격에
10%를 더해서 덮어씁니다.

⚠️ 반드시 딱 한 번만 실행하세요. 두 번 실행하면 가격이 또 10% 올라가서
   총 21% 오르는 식으로 계속 누적됩니다.

필요한 환경변수:
  SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET
  (기존 GitHub Actions Secrets와 동일한 이름)

사용법:
  python bump_ozwear_prices.py --percent 10 --dry-run   # 먼저 미리보기만
  python bump_ozwear_prices.py --percent 10             # 실제로 적용
"""

import os
import sys
import time
import argparse
import requests

API_VERSION = "2024-01"
TARGET_VENDOR = "OZWEAR UGG"


def get_access_token(store, client_id, client_secret):
    store = store.replace("https://", "").replace("http://", "").strip("/")
    url = f"https://{store}/admin/oauth/access_token"
    resp = requests.post(
        url,
        json={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def normalize_vendor(v):
    return " ".join((v or "").split()).strip().upper()


def fetch_all_active_products(store, token):
    store = store.replace("https://", "").replace("http://", "").strip("/")
    products = []
    url = f"https://{store}/admin/api/{API_VERSION}/products.json"
    params = {"limit": 250, "status": "active"}
    headers = {"X-Shopify-Access-Token": token}

    while url:
        resp = requests.get(url, params=params, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        products.extend(data.get("products", []))

        link = resp.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        url = next_url
        params = None

    return products


def update_variant_price(store, token, variant_id, new_price):
    store = store.replace("https://", "").replace("http://", "").strip("/")
    url = f"https://{store}/admin/api/{API_VERSION}/variants/{variant_id}.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    payload = {"variant": {"id": variant_id, "price": f"{new_price:.2f}"}}

    for attempt in range(3):
        resp = requests.put(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return True
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", 2))
            time.sleep(wait)
            continue
        print(f"  ! 실패 (variant {variant_id}): {resp.status_code} - {resp.text[:200]}")
        return False
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--percent", type=float, required=True, help="더할 퍼센트 (예: 10)")
    parser.add_argument("--dry-run", action="store_true", help="실제로 바꾸지 않고 미리보기만")
    args = parser.parse_args()

    store = os.environ["SHOPIFY_STORE"]
    client_id = os.environ["SHOPIFY_CLIENT_ID"]
    client_secret = os.environ["SHOPIFY_CLIENT_SECRET"]

    token = get_access_token(store, client_id, client_secret)

    print("전체 활성 상품 조회 중...")
    all_products = fetch_all_active_products(store, token)
    target_products = [p for p in all_products if normalize_vendor(p.get("vendor")) == normalize_vendor(TARGET_VENDOR)]
    print(f"OZWEAR 상품 {len(target_products)}개 발견")

    multiplier = 1 + (args.percent / 100)
    total_variants = 0
    updated = 0
    failed = 0

    for p in target_products:
        for v in p.get("variants", []):
            total_variants += 1
            old_price = float(v.get("price") or 0)
            new_price = round(old_price * multiplier, 2)

            if args.dry_run:
                if total_variants <= 20:  # 너무 길어지지 않게 앞부분만 미리보기
                    print(f"  [미리보기] {p.get('title')} / SKU {v.get('sku')}: {old_price} -> {new_price}")
                continue

            ok = update_variant_price(store, token, v["id"], new_price)
            if ok:
                updated += 1
            else:
                failed += 1

            if total_variants % 100 == 0:
                print(f"  진행 중... {total_variants}개 처리")

    print("=" * 40)
    if args.dry_run:
        print(f"[미리보기 모드] 총 {total_variants}개 variant가 영향받을 예정입니다 (실제 변경 없음).")
    else:
        print(f"완료: 총 {total_variants}개 중 {updated}개 성공, {failed}개 실패")


if __name__ == "__main__":
    sys.exit(main())
