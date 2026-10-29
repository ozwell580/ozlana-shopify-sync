"""
에버어그 재고 데이터 내려받기 (스마트스토어 연동 준비용)
- main.py 와 같은 방식으로 토큰을 받고 AuStock + SydStock + SydrhStock 를 가져옵니다.
- 창고 3곳을 바코드 기준으로 합산해서 everugg_stock.json 으로 저장합니다.
- 스마트스토어/쇼피파이는 건드리지 않습니다 (조회만).
"""

import os
import json
import time
import collections
import requests

EVERUGG_BASE_URL = os.environ.get("EVERUGG_BASE_URL") or "http://api.everugg.net.au:9990"
EVERUGG_USER_ID = os.environ.get("EVERUGG_USER_ID")
EVERUGG_PASSWORD = os.environ.get("EVERUGG_PASSWORD")

WAREHOUSES = ["/Api/Stock/AuStock", "/Api/Stock/SydStock", "/Api/Stock/SydrhStock"]


def get_token():
    url = f"{EVERUGG_BASE_URL}/Api/Token/getToken"
    params = {"user": EVERUGG_USER_ID, "password": EVERUGG_PASSWORD}
    for attempt in range(3):
        try:
            res = requests.get(url, params=params, timeout=30)
            if res.status_code == 200:
                result = res.json().get("result", {})
                token = result.get("token") if isinstance(result, dict) else None
                if token:
                    print("에버어그 토큰 발급 성공")
                    return token
            print(f"토큰 발급 실패 ({attempt + 1}차): {res.status_code}")
        except Exception as e:
            print(f"토큰 발급 예외 ({attempt + 1}차): {e}")
        time.sleep(10 * (attempt + 1))
    raise SystemExit("에버어그 토큰을 받지 못했습니다.")


def fetch(path, token):
    url = f"{EVERUGG_BASE_URL.rstrip('/')}{path}"
    for attempt in range(3):
        try:
            res = requests.get(url, params={"token": token},
                               headers={"Accept": "application/json"}, timeout=60)
            res.raise_for_status()
            body = res.json()
            if isinstance(body, list):
                return body
            if isinstance(body, dict):
                for key in ("result", "data", "items", "list"):
                    v = body.get(key)
                    if isinstance(v, list):
                        return v
                    if isinstance(v, dict):
                        for k2 in ("data", "items", "list", "result"):
                            if isinstance(v.get(k2), list):
                                return v[k2]
            print(f"{path}: 예상과 다른 응답 형식")
            return []
        except Exception as e:
            print(f"{path} 실패 ({attempt + 1}차): {e}")
            time.sleep(10 * (attempt + 1))
    return []


def main():
    if not EVERUGG_USER_ID or not EVERUGG_PASSWORD:
        raise SystemExit("EVERUGG_USER_ID / EVERUGG_PASSWORD 시크릿이 없습니다.")
    token = get_token()

    combined = {}
    for path in WAREHOUSES:
        rows = fetch(path, token)
        print(f"{path}: {len(rows)}건")
        for item in rows:
            if not isinstance(item, dict):
                continue
            barcode = str(item.get("Barcode", "")).strip()
            if not barcode:
                continue
            qty = int(item.get("AvaiStockQty", 0) or 0)
            if barcode not in combined:
                combined[barcode] = dict(item)
                combined[barcode]["AvaiStockQty"] = qty
            else:
                combined[barcode]["AvaiStockQty"] += qty

    items = list(combined.values())
    with open("everugg_stock.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)

    print(f"\n합산 SKU 수: {len(items)}")
    if items:
        print("필드 목록:", sorted(items[0].keys()))
        print("첫 번째 데이터:", json.dumps(items[0], ensure_ascii=False)[:500])
    codes = {str(i.get("ProductCode", "")).strip() for i in items}
    print("상품코드 수:", len(codes))
    sizes = collections.Counter(str(i.get("Size", "")).strip() for i in items)
    print("사이즈 종류:", sorted(sizes))
    for c in ["AS2112M", "AS3138", "AS7027", "AS3166K", "AS7055K", "ASA047", "ASZ058", "15901"]:
        print(f"  {c}: {'있음' if c in codes else '없음'}")


if __name__ == "__main__":
    main()
