"""
DK UGG API 연결 진단 테스트 (v2)
- 문서상 주소: POST https://api.dkugg.dreamdaytech.com/api/product_stock?num=1
- 첫 시도에서 404가 나와서, 경로/메서드/바디 형식을 여러 조합으로 시도함
- DKUGG_API_KEY 시크릿이 있으면 인증 헤더 방식도 추가로 시도함
- 성공하면 결과 요약을 출력하고 전체 응답을 dkugg_products.json으로 저장함
"""

import os
import sys
import json
from collections import Counter

import requests

HOSTS = [
    "https://api.dkugg.dreamdaytech.com",
    "http://api.dkugg.dreamdaytech.com",
]
PATHS = [
    "/api/product_stock",
    "/api/product_stock/",
    "/product_stock",
    "/api/productStock",
    "/api/product/stock",
]
API_KEY = os.environ.get("DKUGG_API_KEY", "").strip()
NUM = (os.environ.get("DKUGG_NUM") or "1").strip()  # 1: 실제 수량, 0: 재고 등급


def auth_variants():
    variants = [("인증 없음", {}, {})]
    if API_KEY:
        variants += [
            ("헤더 token", {"token": API_KEY}, {}),
            ("헤더 api_key", {"api_key": API_KEY}, {}),
            ("헤더 Authorization Bearer", {"Authorization": f"Bearer {API_KEY}"}, {}),
            ("헤더 Authorization", {"Authorization": API_KEY}, {}),
            ("헤더 X-API-Key", {"X-API-Key": API_KEY}, {}),
            ("헤더 key", {"key": API_KEY}, {}),
            ("쿼리 key", {}, {"key": API_KEY}),
            ("쿼리 token", {}, {"token": API_KEY}),
        ]
    return variants


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
        if isinstance(inner, list):
            return True, {"products": inner}
    return False, data


def summarize(data):
    products = data.get("products", [])
    print("\n" + "=" * 60)
    print(f"상품 수: {len(products)}")
    sku_count = sum(len(p.get("skus") or []) for p in products)
    print(f"SKU 수: {sku_count}")

    print("\n[카테고리별 상품 수]")
    for cat, cnt in Counter(p.get("category") for p in products).most_common():
        print(f"  {cat}: {cnt}")

    print("\n[브랜드]")
    for b, cnt in Counter(p.get("brand") for p in products).most_common():
        print(f"  {b}: {cnt}")

    stock_values = Counter()
    numeric = levels = 0
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

    dup = Counter(s.get("id") for p in products for s in (p.get("skus") or []))
    dups = [k for k, v in dup.items() if v > 1]
    print(f"중복 SKU ID: {len(dups)}개 {dups[:20]}")

    pkeys, skeys = set(), set()
    for p in products:
        pkeys |= set(p.keys())
        for s in p.get("skus") or []:
            skeys |= set(s.keys())
    print(f"\n상품 필드 전체: {sorted(pkeys)}")
    print(f"SKU 필드 전체: {sorted(skeys)}")

    print("\n[샘플 상품 3개]")
    for p in products[:3]:
        sample = dict(p)
        sample["skus"] = (p.get("skus") or [])[:5]
        print(json.dumps(sample, ensure_ascii=False, indent=2))

    for p in products[:1]:
        img = p.get("image")
        if img:
            for url in (img.replace("http://", "https://", 1), img):
                try:
                    r = requests.get(url, timeout=20)
                    print(f"\n이미지 확인 {url} -> {r.status_code}, "
                          f"Content-Type: {r.headers.get('Content-Type')}")
                except Exception as e:
                    print(f"\n이미지 확인 {url} -> 실패: {e}")


def try_request(method, url, headers, params, body_mode):
    h = dict(headers)
    kwargs = {"params": params, "timeout": 60, "allow_redirects": False}
    if method == "POST":
        if body_mode == "json":
            h["Content-Type"] = "application/json"
            kwargs["json"] = {}
        elif body_mode == "json_num":
            h["Content-Type"] = "application/json"
            kwargs["json"] = {"num": int(NUM)}
        elif body_mode == "form":
            kwargs["data"] = {"num": NUM}
    return requests.request(method, url, headers=h, **kwargs)


def main():
    # 0) 서버 자체 응답 확인
    print("=== 서버 기본 응답 확인 ===")
    for host in HOSTS:
        try:
            r = requests.get(host + "/", timeout=30, allow_redirects=False)
            print(f"GET {host}/ -> {r.status_code} | {r.text[:150]!r}")
        except Exception as e:
            print(f"GET {host}/ -> 실패: {e}")

    try:
        ip = requests.get("https://api.ipify.org", timeout=15).text
        print(f"\n이번 실행 서버의 IP: {ip}  (IP 등록이 필요한 API라면 참고)")
    except Exception:
        pass

    if not API_KEY:
        print("\n[안내] DKUGG_API_KEY 시크릿 없음 - 인증 없음 방식만 시도합니다.")

    # 1) 경로/메서드/바디/인증 조합 시도
    print("\n=== 조합 시도 ===")
    combos = []
    for host in HOSTS:
        for path in PATHS:
            for method, body_mode in (("POST", "json"), ("POST", "json_num"),
                                      ("POST", "form"), ("GET", None)):
                combos.append((host, path, method, body_mode))

    status_counter = Counter()
    for auth_name, headers, extra_params in auth_variants():
        for host, path, method, body_mode in combos:
            url = host + path
            params = {"num": NUM, **extra_params}
            label = f"[{auth_name}] {method} {url} body={body_mode}"
            try:
                resp = try_request(method, url, headers, params, body_mode)
            except Exception as e:
                print(f"{label} -> 요청 실패: {e}")
                continue

            status_counter[resp.status_code] += 1
            ok, data = is_success(resp)
            if ok:
                print(f"\n성공: {label}")
                with open("dkugg_products.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                summarize(data)
                return 0

            # 404 외의 응답은 단서가 되므로 내용까지 출력
            if resp.status_code == 404:
                print(f"{label} -> 404")
            else:
                loc = resp.headers.get("Location")
                extra = f" | Location: {loc}" if loc else ""
                print(f"{label} -> {resp.status_code}{extra} | {resp.text[:300]!r}")

    print(f"\n상태코드 집계: {dict(status_counter)}")
    print("모든 조합 실패 - 404가 아닌 응답이 있으면 그 내용이 단서입니다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
