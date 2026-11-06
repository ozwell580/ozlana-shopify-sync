"""
오즈라나 /stocks API 응답 확인용 (조회만 — 스마트스토어/쇼피파이는 건드리지 않음)
- 응답 원본을 ozlana_stock_raw.json 으로 저장
- 상품/재고 항목에 어떤 필드가 있는지 (창고 구분 필드가 있는지) 요약해서 ozlana_stock_summary.txt 로 저장
- OZ3005 / OZ3006 등 확인하고 싶은 코드가 응답에 있는지도 표시
"""

import os
import json
import time
import collections
import requests

OZLANA_BASE_URL = os.environ.get("OZLANA_BASE_URL") or "http://www.ozlanacms.com.au:30008"
OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
CHECK_CODES = [c.strip().upper() for c in os.environ.get("CHECK_CODES", "OZ0035,OZ0036,OZ3005,OZ3006").split(",") if c.strip()]
WAREHOUSE_HINTS = ("ware", "house", "store", "stock", "location", "loc", "depot", "region",
                   "country", "cn", "china", "au", "site", "wh")

lines = []


def to_int(v):
    try:
        return int(float(v))
    except Exception:
        return 0


def log(s=""):
    print(s)
    lines.append(str(s))


def get(path, params=None):
    for attempt in range(3):
        try:
            r = requests.get(f"{OZLANA_BASE_URL}{path}", headers={"X-Token": OZLANA_TOKEN},
                             params=params, timeout=120)
            return r
        except Exception as e:
            print(f"{path} 실패 ({attempt + 1}차): {e}")
            time.sleep(10 * (attempt + 1))
    return None


def main():
    if not OZLANA_TOKEN:
        raise SystemExit("OZLANA_TOKEN 시크릿이 없습니다.")

    r = get("/stocks")
    if r is None:
        raise SystemExit("/stocks 호출 실패")
    log(f"/stocks -> HTTP {r.status_code}")
    body = r.json()
    with open("ozlana_stock_raw.json", "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)

    log(f"최상위 필드: {list(body.keys()) if isinstance(body, dict) else type(body).__name__}")
    raw = body.get("data", []) if isinstance(body, dict) else body
    prods = json.loads(raw) if isinstance(raw, str) else raw
    prods = [p for p in (prods or []) if isinstance(p, dict)]
    log(f"상품(색상) 행 수: {len(prods)}")

    prod_keys = collections.Counter()
    stock_keys = collections.Counter()
    values = collections.defaultdict(collections.Counter)
    for p in prods:
        prod_keys.update(p.keys())
        for k, v in p.items():
            if not isinstance(v, (list, dict)):
                values[("상품", k)][str(v)[:40]] += 1
        for st in p.get("stocks") or []:
            if isinstance(st, dict):
                stock_keys.update(st.keys())
                for k, v in st.items():
                    if not isinstance(v, (list, dict)):
                        values[("재고", k)][str(v)[:40]] += 1

    log("\n[상품 행 필드]  (필드명: 등장 횟수 / 서로 다른 값 개수 / 예시값)")
    for k, n in prod_keys.most_common():
        vc = values[("상품", k)]
        log(f"  {k}: {n} / {len(vc)} / {[v for v, _ in vc.most_common(5)]}")
    log("\n[stocks 안 필드]")
    for k, n in stock_keys.most_common():
        vc = values[("재고", k)]
        log(f"  {k}: {n} / {len(vc)} / {[v for v, _ in vc.most_common(5)]}")

    log("\n[창고 구분일 수 있는 필드]")
    found = False
    for (lvl, k), vc in values.items():
        if any(h in k.lower() for h in WAREHOUSE_HINTS) and k not in ("stockNum",):
            log(f"  {lvl}.{k}: 값 종류 {dict(vc.most_common(10))}")
            found = True
    if not found:
        log("  없음 (재고는 상품·색상·사이즈별 숫자 하나로만 옴)")

    log("\n[같은 코드·색상이 여러 번 나오는지 (창고별로 따로 오는 경우 확인)]")
    dup = collections.Counter((str(p.get("prodMark", "")).upper(), str(p.get("colorName", ""))) for p in prods)
    dups = [(k, n) for k, n in dup.items() if n > 1]
    log(f"  중복 {len(dups)}건 {dups[:10]}")

    log("\n[확인 코드]")
    for code in CHECK_CODES:
        hits = [p for p in prods if str(p.get("prodMark", "")).upper() in (code, "OZ3" + code[2:] if code.startswith("OZ") else code)]
        if not hits:
            log(f"  {code}: 응답에 없음")
            continue
        for p in hits:
            sts = [(s.get("sizeRemark"), s.get("stockNum")) for s in (p.get("stocks") or []) if isinstance(s, dict)]
            log(f"  {code}: 색상 {p.get('colorName')} / 재고 {sts}")
            log(f"     원본: {json.dumps(p, ensure_ascii=False)[:600]}")

    log("\n[전체 상품코드 목록]  코드 | 상품명 | 색상(재고합) | 사이즈 | 가격")
    bycode = collections.OrderedDict()
    for p in prods:
        bycode.setdefault(str(p.get("prodMark", "")).strip().upper(), []).append(p)
    for code in sorted(bycode):
        ps = bycode[code]
        cols = ", ".join(f"{str(x.get('colorName')).strip()}({sum(to_int(s.get('stockNum')) for s in (x.get('stocks') or []))})" for x in ps)
        sizes = sorted({str(s.get("sizeRemark")) for x in ps for s in (x.get("stocks") or [])})
        log(f"  {code} | {str(ps[0].get('prodName')).strip()} | {cols} | {' '.join(sizes)} | "
            f"trade {ps[0].get('prodTradePrice')} min {ps[0].get('prodMinRetailPrice')} rrp {ps[0].get('prodMarketPrice')}")

    log("\n[예시 원본 2건]")
    for p in prods[:2]:
        log("  " + json.dumps(p, ensure_ascii=False)[:800])

    log("\n[다른 엔드포인트 응답 여부 (조회만)]")
    for path in ["/warehouses", "/warehouse", "/stocks/cn", "/stocks/china", "/cnstocks", "/stocks?warehouse=cn"]:
        rr = get(path)
        log(f"  {path} -> {rr.status_code if rr is not None else '실패'}"
            + (f"  {rr.text[:200]}" if rr is not None and rr.status_code == 200 else ""))

    log("\n[같은 상품 안에 같은 사이즈가 여러 번 나오는지]")
    dsz = 0
    for p in prods:
        c = collections.Counter(str(s.get("sizeRemark")) for s in (p.get("stocks") or []) if isinstance(s, dict))
        d = {k: n for k, n in c.items() if n > 1}
        if d:
            dsz += 1
            if dsz <= 5:
                log(f"  {p.get('prodMark')} {p.get('colorName')}: {d}")
    log(f"  중복 사이즈가 있는 상품행: {dsz}")

    def summarize(ps):
        ps = [x for x in (ps or []) if isinstance(x, dict)]
        total = sum(to_int(s.get("stockNum")) for x in ps for s in (x.get("stocks") or []) if isinstance(s, dict))
        marks = {str(x.get("prodMark", "")).upper() for x in ps}
        sample = {}
        for x in ps:
            if str(x.get("prodMark", "")).upper() == "OZ3001" and str(x.get("colorName")) == "BLACK":
                sample = {s.get("sizeRemark"): s.get("stockNum") for s in (x.get("stocks") or [])}
        return len(ps), total, marks, sample

    base = summarize(prods)
    log(f"\n[창고별 조회 시도]  기본 /stocks: 행 {base[0]}, 재고합계 {base[1]}, OZ3001 BLACK {base[3]}")
    for path, params in [("/stocks", {"warehouse_id": 49}), ("/stocks", {"warehouse_id": "49"}), ("/stocks", {"warehouse_id": "55"}),
                         ("/stocks", {"warehouse_id": "SYDNEY"}), ("/stocks", {"warehouse_id": "CHINA"}),
                         ("/stocks", {"warehouse_id": 1}), ("/stocks", {"warehouseId": 55}),
                         ("/stocks", {"warehouse_id": 55}), ("/stocks", {"warehouse": 55}),
                         ("/stocks", {"warehouse": "CHINA"}), ("/stocks", {"whId": 55}),
                         ("/stocks", {"wid": 55}), ("/stocks/55", None), ("/stocks/49", None),
                         ("/warehouses/55/stocks", None), ("/warehouse/55/stocks", None)]:
        rr = get(path, params)
        if rr is None or rr.status_code != 200:
            log(f"  {path} {params} -> {rr.status_code if rr is not None else '실패'}")
            continue
        try:
            d = rr.json().get("data", [])
            d = json.loads(d) if isinstance(d, str) else d
        except Exception:
            log(f"  {path} {params} -> 200 (JSON 아님) {rr.text[:100]}")
            continue
        sm = summarize(d)
        same = "기본과 같음" if (sm[0], sm[1]) == (base[0], base[1]) else "기본과 다름!"
        extra = sorted(sm[2] - base[2])
        log(f"  {path} {params} -> 행 {sm[0]}, 재고합계 {sm[1]} ({same}) OZ3001 BLACK {sm[3]}"
            + (f" 추가코드 {extra[:20]}" if extra else "")
            + (f" OZ3005/3006 있음" if {"OZ3005", "OZ3006"} & sm[2] else ""))

    log("\n[새 연동 모듈 ozlana_api.get_all_stocks() 결과 (시드니+중국 합산)]")
    try:
        import ozlana_api
        merged = ozlana_api.get_all_stocks()
        if merged is None:
            log("  조회 실패")
        else:
            tot = sum(to_int(s.get("stockNum")) for x in merged for s in (x.get("stocks") or []))
            cn = sum(1 for x in merged for s in (x.get("stocks") or []) if s.get("warehouseStocks", {}).get("55"))
            log(f"  창고별: {ozlana_api.summary_text()} | 합산 상품행 {len(merged)}, 재고합계 {tot}, 중국재고 있는 옵션 {cn}")
    except Exception as e:
        log(f"  에러: {e}")

    with open("ozlana_stock_summary.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
