"""오즈라나 API 공용 모듈 (API 문서 v1.20261005, 다중 창고 지원)

- GET/POST /warehouses           -> 창고 목록  (예: 49 SYDNEY, 55 CHINA)
- GET /stocks?warehouse_id=xx    -> 창고별 재고 (warehouse_id 없으면 기본 49 시드니)

get_all_stocks() 는 모든 창고의 /stocks 를 받아서
같은 상품(상품코드+색상)·같은 사이즈 재고를 합친 목록을 돌려줌.
반환 형식은 기존 /stocks 응답의 data 와 똑같아서 기존 코드 그대로 사용 가능.

환경변수
- OZLANA_TOKEN          (필수) 오즈라나 X-Token
- OZLANA_BASE_URL       (선택) 기본 http://www.ozlanacms.com.au:30008
- OZLANA_WAREHOUSE_IDS  (선택) 합칠 창고 ID, 예 "49" (시드니만) / "49,55" (시드니+중국)
                        비워두면 /warehouses 로 받은 전체 창고를 합침
"""
import collections
import json
import os
import time

import requests

DEFAULT_WAREHOUSE_ID = 49
FALLBACK_WAREHOUSES = [{"id": 49, "name": "SYDNEY"}, {"id": 55, "name": "CHINA"}]

BASE_URL = (os.environ.get("OZLANA_BASE_URL") or "http://www.ozlanacms.com.au:30008").rstrip("/")
TOKEN = os.environ.get("OZLANA_TOKEN")

# 마지막 조회 결과 요약 (리포트용)  예: {"SYDNEY(49)": 11907, "CHINA(55)": 0}
LAST_SUMMARY = {}


def _data(resp):
    """{"status":"success","data": "...JSON 문자열..." 또는 리스트} -> 파이썬 객체"""
    body = resp.json()
    if str(body.get("status", "success")).lower() != "success":
        raise RuntimeError(f"오즈라나 응답 실패: {body.get('message')}")
    raw = body.get("data", [])
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else []
    return raw or []


def _headers():
    return {"X-Token": TOKEN}


def get_warehouses():
    """[{"id": 49, "name": "SYDNEY"}, {"id": 55, "name": "CHINA"}]"""
    for method in ("GET", "POST"):  # 문서는 POST, 실제로는 GET 도 됨
        try:
            r = requests.request(method, f"{BASE_URL}/warehouses", headers=_headers(), timeout=60)
            if r.status_code == 200:
                ws = [w for w in _data(r) if isinstance(w, dict) and w.get("id") is not None]
                if ws:
                    return ws
        except Exception as e:
            print(f"오즈라나 창고 목록 {method} 실패: {e}")
    print("오즈라나 창고 목록을 못 받아서 기본값(49 SYDNEY, 55 CHINA) 사용")
    return list(FALLBACK_WAREHOUSES)


def get_stocks(warehouse_id=None, retries=3):
    """한 창고의 /stocks. 실패하면 None (0개와 구분)"""
    params = {"warehouse_id": warehouse_id} if warehouse_id is not None else None
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE_URL}/stocks", headers=_headers(), params=params, timeout=120)
            if r.status_code == 200:
                return [p for p in _data(r) if isinstance(p, dict)]
            print(f"오즈라나 /stocks (창고 {warehouse_id}) -> {r.status_code}")
        except Exception as e:
            print(f"오즈라나 /stocks (창고 {warehouse_id}) 실패 ({attempt + 1}차): {e}")
        if attempt < retries - 1:
            time.sleep(10 * (attempt + 1))
    return None


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _selected_warehouses():
    ids = [x.strip() for x in (os.environ.get("OZLANA_WAREHOUSE_IDS") or "").split(",") if x.strip()]
    all_ws = get_warehouses()
    if not ids:
        return all_ws
    names = {str(w["id"]): w.get("name", "") for w in all_ws}
    return [{"id": int(i) if i.isdigit() else i, "name": names.get(i, "")} for i in ids]


def get_all_stocks():
    """모든(또는 지정한) 창고 재고를 합친 /stocks 형식 목록.
    기본 창고(49 시드니) 조회가 실패하면 None -> 기존 코드처럼 '재고 유지' 처리.
    다른 창고(중국 등)가 실패하면 그 창고만 빼고 진행."""
    LAST_SUMMARY.clear()
    merged = collections.OrderedDict()  # (상품코드, 색상) -> 상품 dict (stocks 합산)
    got_default = False
    warehouses = _selected_warehouses()
    need_default = any(str(w["id"]) == str(DEFAULT_WAREHOUSE_ID) for w in warehouses)

    for w in warehouses:
        wid, wname = w["id"], str(w.get("name") or "").strip()
        label = f"{wname}({wid})" if wname else str(wid)
        prods = get_stocks(wid)
        if prods is None:
            LAST_SUMMARY[label] = "조회 실패"
            print(f"오즈라나 창고 {label}: 조회 실패 -> 이 창고는 제외")
            continue
        if str(wid) == str(DEFAULT_WAREHOUSE_ID):
            got_default = True

        total = 0
        for p in prods:
            key = (str(p.get("prodMark", "")).strip().upper(), str(p.get("colorName", "")).strip().upper())
            if not key[0]:
                continue
            if key not in merged:
                base = {k: v for k, v in p.items() if k != "stocks"}
                base["stocks"] = []
                base["_size_index"] = {}
                merged[key] = base
            m = merged[key]
            for st in p.get("stocks") or []:
                if not isinstance(st, dict):
                    continue
                n = max(_to_int(st.get("stockNum")), 0)
                total += n
                size = str(st.get("sizeRemark", "")).strip()
                idx = m["_size_index"].get(size)
                if idx is None:
                    item = dict(st)
                    item["stockNum"] = n
                    item["warehouseStocks"] = {str(wid): n}
                    m["_size_index"][size] = len(m["stocks"])
                    m["stocks"].append(item)
                else:
                    item = m["stocks"][idx]
                    item["stockNum"] += n
                    item["warehouseStocks"][str(wid)] = item["warehouseStocks"].get(str(wid), 0) + n
                    if not item.get("barCode") and st.get("barCode"):
                        item["barCode"] = st.get("barCode")
        LAST_SUMMARY[label] = total
        print(f"오즈라나 창고 {label}: 상품행 {len(prods)}개, 재고 합계 {total}")

    if need_default and not got_default:
        print("오즈라나 기본 창고(시드니 49) 조회 실패 -> 전체 실패 처리 (재고 유지)")
        return None
    if not merged and not got_default:
        return None

    out = []
    for m in merged.values():
        m.pop("_size_index", None)
        out.append(m)
    return out


def summary_text():
    return ", ".join(f"{k} {v}" for k, v in LAST_SUMMARY.items())
