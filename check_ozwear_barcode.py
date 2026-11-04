"""
오즈웨어 API 응답에 바코드(EAN/UPC/GTIN) 정보가 있는지 확인하는 스크립트
- 상품 1~3개의 전체 필드를 그대로 출력
- 바코드로 보이는 필드를 자동으로 찾아서 표시
- 바코드 필드가 있으면 전체 SKU-바코드 목록을 ozwear_barcodes.csv로 저장
"""

import os
import re
import csv
import json
import sys
import requests

# build_shopify_csv.py에 있는 오즈웨어 API 주소와 같은 값을 넣으세요 (끝에 / 없이)
BASE_URL = os.environ.get("OZWEAR_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("OZWEAR_API_KEY", "")
API_SECRET = os.environ.get("OZWEAR_API_SECRET", "")

BARCODE_PATTERN = re.compile(r"(barcode|bar_code|ean|upc|gtin|jan|isbn)", re.IGNORECASE)


def get_token():
    url = f"{BASE_URL}/token"
    payload = {"key": API_KEY, "secret": API_SECRET}

    # JSON 방식 먼저 시도, 안 되면 form 방식
    for kwargs in ({"json": payload}, {"data": payload}):
        try:
            r = requests.post(url, timeout=60, **kwargs)
        except Exception as e:
            print(f"토큰 요청 오류: {e}")
            continue
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                return r.text.strip().strip('"')
            if isinstance(data, str):
                return data
            for k in ("token", "access_token", "api_key", "Token", "data"):
                v = data.get(k) if isinstance(data, dict) else None
                if isinstance(v, str):
                    return v
                if isinstance(v, dict):
                    for kk in ("token", "access_token", "api_key"):
                        if isinstance(v.get(kk), str):
                            return v[kk]
            print("토큰 응답 형식을 알 수 없음:", json.dumps(data)[:500])
            return None
        print(f"토큰 발급 실패 ({r.status_code}): {r.text[:300]}")
    return None


def extract_list(data):
    """응답에서 상품 리스트 부분을 찾아냄"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("products", "data", "items", "result", "Products"):
            if isinstance(data.get(k), list):
                return data[k]
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def find_barcode_fields(obj, prefix=""):
    """중첩된 구조까지 뒤져서 바코드처럼 보이는 필드 경로를 찾음"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if BARCODE_PATTERN.search(str(k)):
                found.append((path, v))
            found.extend(find_barcode_fields(v, path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):
            found.extend(find_barcode_fields(item, f"{prefix}[{i}]"))
    return found


def find_13digit_values(obj, prefix=""):
    """필드 이름과 상관없이 바코드처럼 생긴 숫자(8/12/13/14자리)를 찾음"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (str, int)) and re.fullmatch(r"\d{8}|\d{12,14}", str(v).strip()):
                found.append((path, v))
            found.extend(find_13digit_values(v, path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):
            found.extend(find_13digit_values(item, f"{prefix}[{i}]"))
    return found


def get_value(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                return v
    return None


def main():
    if not BASE_URL or not API_KEY or not API_SECRET:
        print("OZWEAR_BASE_URL / OZWEAR_API_KEY / OZWEAR_API_SECRET 환경변수를 확인하세요.")
        sys.exit(1)

    token = get_token()
    if not token:
        sys.exit(1)
    print("토큰 발급 성공\n")

    headers = {"api_key": token}
    all_hits = {}

    for endpoint in ("/products", "/products/stock"):
        print("=" * 70)
        print(f"엔드포인트: {endpoint}")
        print("=" * 70)
        r = requests.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=120)
        if r.status_code != 200:
            print(f"요청 실패 ({r.status_code}): {r.text[:300]}\n")
            continue

        data = r.json()
        items = extract_list(data)
        print(f"상품 수: {len(items)}\n")

        print("--- 샘플 상품 전체 필드 (최대 2개) ---")
        for item in items[:2]:
            print(json.dumps(item, ensure_ascii=False, indent=2)[:4000])
            print()

        hits = find_barcode_fields(items[:3])
        digit_hits = find_13digit_values(items[:3])

        print("--- 이름으로 찾은 바코드 후보 필드 ---")
        if hits:
            for path, v in hits:
                print(f"  {path} = {v}")
        else:
            print("  없음")

        print("--- 바코드처럼 생긴 숫자 값 (8/12/13/14자리) ---")
        if digit_hits:
            for path, v in digit_hits:
                print(f"  {path} = {v}")
        else:
            print("  없음")
        print()

        if hits and endpoint not in all_hits:
            all_hits[endpoint] = (items, hits)

    # 바코드 필드가 최상위에 있으면 CSV로 저장
    for endpoint, (items, hits) in all_hits.items():
        top_level_keys = [p for p, _ in hits if "." not in p.split("]", 1)[-1].lstrip(".")]
        barcode_key = None
        for p, _ in hits:
            key = p.split(".")[-1].split("]")[-1]
            if key and key in (items[0] if items and isinstance(items[0], dict) else {}):
                barcode_key = key
                break
        if not barcode_key:
            continue

        sku_key = None
        sample = items[0]
        for cand in ("sku", "SKU", "Sku", "code", "barcode_sku", "item_code", "ItemCode", "style_code"):
            if cand in sample:
                sku_key = cand
                break

        out = "ozwear_barcodes.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["sku", "barcode", "raw"])
            for it in items:
                w.writerow([
                    get_value(it, sku_key) if sku_key else "",
                    get_value(it, barcode_key),
                    json.dumps(it, ensure_ascii=False)[:500],
                ])
        print(f"바코드 목록 저장 완료: {out} ({len(items)}건, 바코드 필드: {barcode_key}, SKU 필드: {sku_key})")
        break
    else:
        print("결론: 이름으로 확인되는 바코드 필드가 없습니다. 위 '바코드처럼 생긴 숫자 값' 결과를 확인해 주세요.")


if __name__ == "__main__":
    main()
