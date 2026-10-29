"""
DK UGG 재고 API 테스트 스크립트
- DK UGG 재고 API를 호출해서 실제 응답이 어떻게 오는지 확인합니다.
- 결과 전체를 dk_stock.json 으로 저장하고, 요약을 로그에 출력합니다.
- 스마트스토어 수정은 하지 않습니다 (조회만).
"""

import json
import collections
import requests

BASE_URL = "https://api.dkugg.dreamdaytech.com"
ENDPOINT = "/api/product_stock"


def call_api():
    url = BASE_URL + ENDPOINT
    headers = {"content-type": "application/json"}

    # 문서상 num=1 이면 실제 수량, 0 이면 등급(sufficient/shortage/out)
    attempts = [
        ("쿼리에 num=1", dict(params={"num": 1}, json={})),
        ("바디에 num=1", dict(json={"num": 1})),
        ("파라미터 없음", dict(json={})),
    ]

    for label, kwargs in attempts:
        print(f"\n=== 시도: {label} ===")
        try:
            r = requests.post(url, headers=headers, timeout=120, **kwargs)
        except Exception as e:
            print("요청 실패:", e)
            continue
        print("HTTP 상태:", r.status_code)
        print("응답 앞부분:", r.text[:500])
        if r.status_code == 200:
            try:
                return label, r.json()
            except Exception as e:
                print("JSON 변환 실패:", e)
    return None, None


def summarize(data):
    products = data.get("products") if isinstance(data, dict) else None
    if products is None:
        print("products 키가 없습니다. 최상위 키:", list(data.keys()) if isinstance(data, dict) else type(data))
        return

    print(f"\n상품 수: {len(products)}")
    ids = [p.get("id") for p in products]
    prefix = collections.Counter(str(i)[:2] for i in ids)
    print("상품ID 앞 2글자 분포:", dict(prefix))
    print("상품ID 예시 30개:", ids[:30])

    colors = collections.Counter()
    sizes = collections.Counter()
    stocks = collections.Counter()
    sku_count = 0
    for p in products:
        for s in p.get("skus", []) or []:
            sku_count += 1
            colors[s.get("color")] += 1
            sizes[s.get("size")] += 1
            st = s.get("stock")
            stocks["숫자" if str(st).lstrip("-").isdigit() else str(st)] += 1

    print(f"SKU 수: {sku_count}")
    print("\n색상 목록:", sorted(colors))
    print("\n사이즈 목록:", sorted(map(str, sizes)))
    print("\n재고 값 형태:", dict(stocks))

    print("\n샘플 상품 3개:")
    for p in products[:3]:
        print(json.dumps(p, ensure_ascii=False)[:800])

    # 스마트스토어 코드 중 끝에 A가 붙은 것들이 API에 있는지 확인
    check = ["DK001A", "DK002A", "DK003A", "DK004A", "DK006A", "DK081A",
             "DK001", "DK095", "DK135", "DK137", "DK151", "DK152", "DK155",
             "DK244", "DB017", "DB143", "DB237", "DB091", "DS111", "DH001"]
    idset = set(map(str, ids))
    print("\n코드 존재 여부 확인:")
    for c in check:
        print(f"  {c}: {'있음' if c in idset else '없음'}")


def main():
    label, data = call_api()
    if data is None:
        print("\n모든 시도가 실패했습니다. 위 HTTP 상태와 응답을 확인해주세요.")
        raise SystemExit(1)

    print(f"\n성공한 방식: {label}")
    with open("dk_stock.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("dk_stock.json 저장 완료")
    summarize(data)


if __name__ == "__main__":
    main()
