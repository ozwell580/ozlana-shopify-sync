"""
시드니셀러 커머스API 상품 구조 확인 (읽기 전용 + 빈 요청 검증)
- 전체 상품 목록 요약 저장
- 옵션 유형별 샘플 상품 원본 데이터 저장
- 옵션 재고 변경 API에 '빈 요청'을 보내서 필요한 필드만 확인 (빈 요청은 검증 오류로 끝나서 아무것도 바뀌지 않음)
결과: naver_probe/ 폴더
"""

import base64
import json
import os
import sys
import time

import bcrypt
import requests

API = "https://api.commerce.naver.com/external"
CLIENT_ID = os.environ.get("SYDNEY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SYDNEY_CLIENT_SECRET", "").strip()
PROXY = os.environ.get("NAVER_PROXY", "").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None
OUT = "naver_probe"
os.makedirs(OUT, exist_ok=True)


def save(name, data):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def token():
    ts = str(int(time.time() * 1000))
    sign = base64.b64encode(bcrypt.hashpw(f"{CLIENT_ID}_{ts}".encode(), CLIENT_SECRET.encode())).decode()
    r = requests.post(f"{API}/v1/oauth2/token", data={
        "client_id": CLIENT_ID, "timestamp": ts, "client_secret_sign": sign,
        "grant_type": "client_credentials", "type": "SELF"}, proxies=PROXIES, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def call(method, path, tok, body=None):
    for attempt in range(5):
        r = requests.request(method, f"{API}{path}", headers={
            "Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            data=json.dumps(body) if body is not None else None, proxies=PROXIES, timeout=60)
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        return r
    return r


def main():
    tok = token()
    print("토큰 발급 성공")

    # 1) 전체 목록
    items, page = [], 1
    while True:
        r = call("POST", "/v1/products/search", tok, {"page": page, "size": 100})
        r.raise_for_status()
        d = r.json()
        items += d.get("contents", [])
        if page >= (d.get("totalPages") or 1):
            break
        page += 1
        time.sleep(0.3)
    print(f"상품 {len(items)}개 조회")
    save("search_first2.json", items[:2])
    summary = []
    for it in items:
        for ch in it.get("channelProducts", []):
            summary.append({"originProductNo": it.get("originProductNo"),
                            "channelProductNo": ch.get("channelProductNo"),
                            "name": ch.get("name"), "sellerManagementCode": ch.get("sellerManagementCode"),
                            "brandName": ch.get("brandName"), "statusType": ch.get("statusType"),
                            "stockQuantity": ch.get("stockQuantity")})
    save("products_summary.json", summary)

    # 2) 샘플 상세: 옵션 유형별로 최대 2개씩
    kinds = {}
    for it in items[:400]:
        no = it.get("originProductNo")
        r = call("GET", f"/v2/products/origin-products/{no}", tok)
        if r.status_code != 200:
            print(f"상세 조회 실패 {no}: {r.status_code} {r.text[:300]}")
            continue
        d = r.json()
        oi = (((d.get("originProduct") or {}).get("detailAttribute") or {}).get("optionInfo")) or {}
        if oi.get("optionCombinations"):
            k = "combination"
        elif oi.get("optionStandards"):
            k = "standard"
        elif oi.get("optionSimple"):
            k = "simple"
        elif oi:
            k = "other"
            print(f"기타 옵션 구조 {no}: {sorted(oi.keys())}")
        else:
            k = "none"
        disc = bool(((d.get("originProduct") or {}).get("customerBenefit") or {}).get("immediateDiscountPolicy"))
        k2 = f"{k}{'_disc' if disc else ''}"
        kinds.setdefault(k2, [])
        if len(kinds[k2]) < 2:
            kinds[k2].append(no)
            save(f"detail_{k2}_{no}.json", d)
        time.sleep(0.25)
        if all(len(v) >= 2 for v in kinds.values()) and len(kinds) >= 5:
            break
    print("옵션 유형별 샘플:", json.dumps(kinds, ensure_ascii=False))

    # 3) 옵션 재고 변경 API 존재/필드 확인 (빈 요청 -> 검증 오류, 변경 없음)
    # 실제 상품을 건드리지 않도록 존재하지 않는 상품번호(1)로만 보냄
    probes = {}
    path = "/v1/products/origin-products/1/option-stock"
    tries = {
        "empty_optionInfo": {"optionInfo": {}},
        "combination_only": {"optionInfo": {"optionCombinations": [{"id": 1, "stockQuantity": 0}]}},
        "combination_full": {"productSalePrice": {"salePrice": 10000},
                             "optionInfo": {"optionCombinations": [{"id": 1, "stockQuantity": 0, "price": 0,
                                                                    "usable": True}]}},
    }
    for label, body in tries.items():
        r = call("PUT", path, tok, body)
        probes[label] = {"status": r.status_code, "body": r.text[:3000]}
        print(f"PUT option-stock ({label}) -> {r.status_code}\n{r.text[:1500]}")
    save("probes.json", probes)


if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("SYDNEY_CLIENT_ID / SYDNEY_CLIENT_SECRET 없음")
    main()
