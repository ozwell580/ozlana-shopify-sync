"""
DK UGG API 연결 테스트
- POST https://api.dkugg.dreamdaytech.com/api/product_stock?num=1
- 문서에 인증 헤더가 명시되어 있지 않아서, 인증 없이 먼저 시도하고
  실패하면 DKUGG_API_KEY 시크릿을 여러 헤더 방식으로 넣어 순서대로 시도함
- 결과 요약을 로그에 출력하고 전체 응답을 dkugg_products.json으로 저장함
"""

import os
import sys
import json
from collections import Counter

import requests

BASE_URL = "https://api.dkugg.dreamdaytech.com"
ENDPOINT = "/api/product_stock"
API_KEY = os.environ.get("DKUGG_API_KEY", "").strip()
NUM = os.environ.get("DKUGG_NUM", "1").strip()  # 1: 실제 수량, 0: 재고 등급


def build_attempts():
    base_headers = {"Content-Type": "application/json"}
    attempts = [("인증 없음", dict(base_headers), {})]
    if API_KEY:
        attempts += [
            ("헤더 api_key", {**base_headers, "api_key": API_KEY}, {}),
            ("헤더 token", {**base_headers, "token": API_KEY}, {}),
            ("헤더 Authorization Bearer", {**base_headers, "Authorization": f"Bearer {API_KEY}"}, {}),
            ("헤더 X-API-Key", {**base_headers, "X-API-Key": API_KEY}, {}),
            ("헤더 key", {**base_headers, "key": API_KEY}, {}),
            ("쿼리 key", dict(base_headers), {"key": API_KEY}),
            ("쿼리 token", dict(base_headers), {"token": API_KEY}),
        ]
    else:
        print("[안내] DKUGG_API_KEY 시크릿이 비어 있음 - 인증 없음 방식만 시도합니다.")
    return attempts


def is_success(resp):
    if resp.status_code != 200:
        return False, None
    try:
        data = resp.json()
    except ValueError:
        return False, None
    if isinstance(data, dict):
        status = data.get("status")
        if status is not None and str(status) != "200":
            return False, data
        if isinstance(data.get("products"), list):
            return True, data
        inner = data.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("products"), list):
            return True, inner
    return False, data


def summarize(data):
    products = data.get("products", [])
    print("\n" + "=" * 60)
    print(f"상품 수: {len(products)}")

    sku_count = sum(len(p.get("skus") or []) for p in products)
    print(f"SKU 수: {sku_count}")

    categories = Counter(p.get("category") for p in products)
    print("\n[카테고리별 상품 수]")
    for cat, cnt in categories.most_common():
        print(f"  {cat}: {cnt}")

    brands = Counter(p.get("brand") for p in products)
    print("\n[브랜드]")
    for b, cnt in brands.most_common():
        print(f"  {b}: {cnt}")

    stock_values = Counter()
    numeric, levels = 0, 0
    for p in products:
        for s in p.get("skus") or []:
            v = s.get("stock")
            try:
                int(str(v))
                numeric += 1
            except ValueError:
                levels += 1
                stock_values[str(v)] += 1
    print(f"\n[재고 값 형태] 숫자: {numeric}개 / 등급 문자: {levels}개")
    for v, cnt in stock_values.most_common():
        print(f"  {v}: {cnt}")

    no_image = [p.get("id") for p in products if not p.get("image")]
    http_image = sum(1 for p in products if str(p.get("image", "")).startswith("http://"))
    print(f"\n이미지 없는 상품: {len(no_image)}개 {no_image[:20]}")
    print(f"http:// 이미지 상품: {http_image}개")

    dup_skus = Counter(s.get("id") for p in products for s in (p.get("skus") or []))
    dups = [k for k, v in dup_skus.items() if v > 1]
    print(f"중복 SKU ID: {len(dups)}개 {dups[:20]}")

    extra_keys = set()
    for p in products:
        extra_keys |= set(p.keys())
    print(f"\n상품 필드 전체: {sorted(extra_keys)}")
    sku_keys = set()
    for p in products:
        for s in p.get("skus") or []:
            sku_keys |= set(s.keys())
    print(f"SKU 필드 전체: {sorted(sku_keys)}")

    print("\n[샘플 상품 3개]")
    for p in products[:3]:
        sample = dict(p)
        sample["skus"] = (p.get("skus") or [])[:5]
        print(json.dumps(sample, ensure_ascii=False, indent=2))

    # 이미지 https 접근 가능 여부 확인 (Shopify 임포트용)
    for p in products[:1]:
        img = p.get("image")
        if img:
            https_img = img.replace("http://", "https://", 1)
            for url in (https_img, img):
                try:
                    r = requests.get(url, timeout=20)
                    print(f"\n이미지 확인 {url} -> {r.status_code}, "
                          f"Content-Type: {r.headers.get('Content-Type')}")
                except Exception as e:
                    print(f"\n이미지 확인 {url} -> 실패: {e}")


def main():
    url = BASE_URL + ENDPOINT
    for name, headers, extra_params in build_attempts():
        params = {"num": NUM, **extra_params}
        print(f"\n--- 시도: {name} ---")
        try:
            resp = requests.post(url, headers=headers, params=params, json={}, timeout=120)
        except Exception as e:
            print(f"요청 실패: {e}")
            continue

        print(f"HTTP {resp.status_code}, 응답 길이 {len(resp.content)} bytes")
        ok, data = is_success(resp)
        if ok:
            print(f"성공: '{name}' 방식으로 연결됨")
            with open("dkugg_products.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            summarize(data)
            return 0
        print(f"응답 앞부분: {resp.text[:500]}")

    print("\n모든 방식 실패 - 위 응답 내용을 확인하세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
