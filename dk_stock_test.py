"""
DK UGG 재고 API 테스트 스크립트 (주소 탐색 버전)
- 문서 주소(POST /api/product_stock)가 404라서
  http/https, GET/POST, 경로 변형을 차례로 시도해서 맞는 주소를 찾습니다.
- 성공하면 결과 전체를 dk_stock.json 으로 저장하고 요약을 출력합니다.
- 스마트스토어 수정은 하지 않습니다 (조회만).
"""

import json
import collections
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
    "/index.php/api/product_stock",
    "/api/v1/product_stock",
]

METHODS = ["POST", "GET"]


def try_one(method, url):
    headers = {"content-type": "application/json"}
    try:
        if method == "POST":
            r = requests.post(url, headers=headers, params={"num": 1},
                              json={}, timeout=60, allow_redirects=True)
        else:
            r = requests.get(url, headers=headers, params={"num": 1},
                             timeout=60, allow_redirects=True)
    except Exception as e:
        print(f"[{method}] {url} -> 요청 실패: {e}")
        return None
    snippet = r.text[:200].replace("\n", " ")
    print(f"[{method}] {url} -> {r.status_code} | {snippet}")
    if r.history:
        print("   리다이렉트:", [h.status_code for h in r.history], "->", r.url)
    if r.status_code == 200:
        try:
            return r.json()
        except Exception:
            print("   200이지만 JSON이 아님")
    return None


def check_root():
    print("=== 서버 기본 주소 확인 ===")
    for host in HOSTS:
        for path in ["/", "/api", "/api/"]:
            try:
                r = requests.get(host + path, timeout=30)
                print(f"[GET] {host}{path} -> {r.status_code} | {r.text[:150].replace(chr(10), ' ')}")
            except Exception as e:
                print(f"[GET] {host}{path} -> 실패: {e}")


def summarize(data):
    products = data.get("products") if isinstance(data, dict) else None
    if products is None:
        print("products 키가 없습니다. 최상위 키:",
              list(data.keys()) if isinstance(data, dict) else type(data))
        print(json.dumps(data, ensure_ascii=False)[:1500])
        return

    print(f"\n상품 수: {len(products)}")
    ids = [p.get("id") for p in products]
    print("상품ID 앞 2글자 분포:", dict(collections.Counter(str(i)[:2] for i in ids)))
    print("상품ID 예시 30개:", ids[:30])

    colors, sizes, stocks = collections.Counter(), collections.Counter(), collections.Counter()
    sku_count = 0
    for p in products:
        for s in p.get("skus", []) or []:
            sku_count += 1
            colors[s.get("color")] += 1
            sizes[str(s.get("size"))] += 1
            st = s.get("stock")
            stocks["숫자" if str(st).lstrip("-").isdigit() else str(st)] += 1

    print(f"SKU 수: {sku_count}")
    print("\n색상 목록:", sorted(map(str, colors)))
    print("\n사이즈 목록:", sorted(sizes))
    print("\n재고 값 형태:", dict(stocks))

    print("\n샘플 상품 3개:")
    for p in products[:3]:
        print(json.dumps(p, ensure_ascii=False)[:800])

    check = ["DK001A", "DK002A", "DK003A", "DK004A", "DK006A", "DK081A",
             "DK001", "DK095", "DK135", "DK137", "DK151", "DK152", "DK155",
             "DK244", "DB017", "DB143", "DB237", "DB091", "DS111", "DH001"]
    idset = set(map(str, ids))
    print("\n코드 존재 여부 확인:")
    for c in check:
        print(f"  {c}: {'있음' if c in idset else '없음'}")


def main():
    check_root()
    print("\n=== 재고 API 주소 탐색 ===")
    for host in HOSTS:
        for path in PATHS:
            for method in METHODS:
                data = try_one(method, host + path)
                if data is not None:
                    print(f"\n성공: [{method}] {host}{path}")
                    with open("dk_stock.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=1)
                    print("dk_stock.json 저장 완료")
                    summarize(data)
                    return
    print("\n모든 주소가 실패했습니다. 위 결과 전체를 보내주세요.")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
