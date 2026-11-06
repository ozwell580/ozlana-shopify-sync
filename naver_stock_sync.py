"""
시드니셀러 재고 자동 연동 (네이버 커머스API)
------------------------------------------------
공급처 재고(DK UGG / 에버어그 / 오즈웨어 / 오즈라나)를 읽어서
시드니셀러 조합형 옵션 상품의 '옵션별 재고'만 커머스API로 갱신합니다.
공급처 조회와 색상·사이즈 맞추기 규칙은 smartstore_stock_sync.py(엑셀 방식)를 그대로 씁니다.

실행 모드 (환경변수 MODE)
  dry-run  : 바꾸지 않고 '바꿀 예정' 보고서만 만듦 (기본값)
  test-one : 바뀌는 상품 중 1개만 실제로 바꾸고, 다시 읽어서 재고 말고 다른 값이 그대로인지 확인
  apply    : 바뀌는 상품 전부 실제로 바꿈 (상품마다 바꾼 뒤 다시 읽어서 확인)

안전장치
  - 가격·옵션가·판매여부·할인은 현재 값을 그대로 다시 보내고 재고 숫자만 바꿈
  - 바꾼 뒤 다시 읽어서 재고 말고 다른 값이 달라졌으면 즉시 멈춤
  - 공급처 조회가 실패한 브랜드는 건너뜀 (재고 유지)
  - 한 브랜드에서 품절(0)로 바뀌는 옵션이 너무 많으면(기본 50% 초과) 공급처 이상으로 보고 그 브랜드는 건너뜀
  - 오즈웨어·오즈라나는 공급처에서 상품을 못 찾으면 재고 유지 (엑셀 방식과 같음)
  - 조합형 옵션 상품만 처리. 옵션 없는 상품, 간편 입력 옵션, 단독형 옵션은 보고서에만 표시

필요한 GitHub 시크릿
  SYDNEY_CLIENT_ID, SYDNEY_CLIENT_SECRET, NAVER_PROXY
  + 공급처 시크릿 (EVERUGG_*, OZLANA_*, OZWEAR_*, SHOPIFY_*)
출력
  naver_stock_report.txt
"""

import base64
import collections
import json
import os
import re
import sys
import time

import bcrypt
import requests

import smartstore_stock_sync as S

API = "https://api.commerce.naver.com/external"
CLIENT_ID = os.environ.get("SYDNEY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SYDNEY_CLIENT_SECRET", "").strip()
PROXY = os.environ.get("NAVER_PROXY", "").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None
MODE = (os.environ.get("MODE") or "dry-run").strip().lower()
MAX_ZERO_RATIO = float(os.environ.get("MAX_ZERO_RATIO", "0.5"))  # 브랜드별 품절 전환 비율 상한
ONLY_CODES = {c.strip().upper() for c in os.environ.get("ONLY_CODES", "").split(",") if c.strip()}
REPORT_FILE = "naver_stock_report.txt"
SLEEP = 0.25

KEEP_STATUS = {"SALE", "OUTOFSTOCK"}  # 판매중·품절 상품만 처리 (판매중지·삭제 등은 건너뜀)


def load_everugg_models(path="everugg_models.txt"):
    """에버어그 가격표 모델번호. 재고 API에 없어도 여기 있으면 재고 유지, 여기도 없으면 품절"""
    try:
        with open(path, encoding="utf-8") as f:
            return {l.strip().upper() for l in f if l.strip() and not l.startswith("#")}
    except FileNotFoundError:
        print(f"⚠️ {path} 없음: 에버어그 가격표 기준을 쓰지 못함")
        return set()


EVERUGG_MODELS = load_everugg_models()


# ================================================================ 네이버 API
class Naver:
    def __init__(self):
        self.tok = None
        self.tok_time = 0

    def token(self):
        if self.tok and time.time() - self.tok_time < 2400:
            return self.tok
        ts = str(int(time.time() * 1000))
        sign = base64.b64encode(bcrypt.hashpw(f"{CLIENT_ID}_{ts}".encode(), CLIENT_SECRET.encode())).decode()
        r = requests.post(f"{API}/v1/oauth2/token", data={
            "client_id": CLIENT_ID, "timestamp": ts, "client_secret_sign": sign,
            "grant_type": "client_credentials", "type": "SELF"}, proxies=PROXIES, timeout=30)
        if r.status_code != 200:
            sys.exit(f"네이버 토큰 발급 실패: HTTP {r.status_code} {r.text[:300]}")
        self.tok = r.json()["access_token"]
        self.tok_time = time.time()
        return self.tok

    def call(self, method, path, body=None):
        r = None
        for attempt in range(6):
            try:
                r = requests.request(method, f"{API}{path}", headers={
                    "Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"},
                    data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
                    proxies=PROXIES, timeout=60)
            except requests.RequestException as e:
                print(f"  네트워크 오류 ({attempt + 1}차): {e}")
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 401:
                self.tok = None
                continue
            return r
        return r

    def list_products(self):
        items, page = [], 1
        while True:
            r = self.call("POST", "/v1/products/search", {"page": page, "size": 100})
            if r is None or r.status_code != 200:
                sys.exit(f"상품 목록 조회 실패: {getattr(r, 'status_code', '?')} {getattr(r, 'text', '')[:300]}")
            d = r.json()
            items += d.get("contents", [])
            if page >= (d.get("totalPages") or 1):
                return items
            page += 1
            time.sleep(SLEEP)

    def get(self, origin_no):
        r = self.call("GET", f"/v2/products/origin-products/{origin_no}")
        if r is None or r.status_code != 200:
            return None, f"HTTP {getattr(r, 'status_code', '?')} {getattr(r, 'text', '')[:200]}"
        return r.json(), None

    def put_option_stock(self, origin_no, body):
        return self.call("PUT", f"/v1/products/origin-products/{origin_no}/option-stock", body)


# ================================================================ 상품 정보 꺼내기
def origin(d):
    return d.get("originProduct") or {}


def opt_info(d):
    return ((origin(d).get("detailAttribute") or {}).get("optionInfo")) or {}


def brand_name(d):
    return (((origin(d).get("detailAttribute") or {}).get("naverShoppingSearchInfo")) or {}).get("brandName") or ""


def seller_code(d):
    return (((origin(d).get("detailAttribute") or {}).get("sellerCodeInfo")) or {}).get("sellerManagementCode") or ""


def discount_policy(d):
    return ((origin(d).get("customerBenefit") or {}).get("immediateDiscountPolicy"))


def group_names(oi):
    g = oi.get("optionCombinationGroupNames") or {}
    return [g.get(f"optionGroupName{i}") for i in (1, 2, 3) if g.get(f"optionGroupName{i}")]


def snapshot(d):
    """재고 말고 바뀌면 안 되는 값들"""
    o = origin(d)
    oi = opt_info(d)
    # statusType은 재고 0 <-> 1 이상이면 네이버가 자동으로 바꾸므로 비교하지 않음
    return {
        "salePrice": o.get("salePrice"),
        "discount": discount_policy(d),
        "options": sorted((c.get("id"), c.get("optionName1"), c.get("optionName2"), c.get("optionName3"),
                           c.get("price"), bool(c.get("usable"))) for c in oi.get("optionCombinations") or []),
    }


def stocks_of(d):
    return {c.get("id"): int(c.get("stockQuantity") or 0) for c in opt_info(d).get("optionCombinations") or []}


# ================================================================ 재고 계산 (엑셀 방식 규칙 그대로)
COL = {"브랜드": 0, "상품명": 1, "판매자 상품코드": 2}


def plan_product(d, sup, R):
    """{옵션id: 새 재고} 또는 None(건드리지 않음)"""
    o = origin(d)
    name = o.get("name") or ""
    code = seller_code(d).upper()
    if not code:
        m = S.CODE_RE.search(name.upper())
        code = m.group(1).upper() if m else ""
    brand = S.brand_of([brand_name(d), name, code], COL)
    if brand not in sup:
        return brand, code, None
    if ONLY_CODES and code not in ONLY_CODES:
        return brand, code, None
    oi = opt_info(d)
    combos = oi.get("optionCombinations") or []
    if not combos:
        kind = "간편 입력 옵션" if oi.get("optionSimple") else ("단독형 옵션" if oi.get("optionStandards") else "옵션 없음")
        R[f"건너뜀: {kind} (재고 유지)"].append(f"[{brand}] {code}  {name}")
        return brand, code, None

    is_oz = brand in S.OZ_BRANDS
    skus = sup[brand].get(S.OZ_CODE_ALIAS.get(code, code))
    if not skus:
        if is_oz:
            R["오즈 공급처에 없는 상품 (재고 유지)"].append(f"[{brand}] {code}  {name}")
            return brand, code, None
        if brand == S.BRAND_EU and code in EVERUGG_MODELS:
            R["에버어그 재고 API엔 없지만 가격표에 있는 상품 (재고 유지)"].append(f"[{brand}] {code}  {name}")
            return brand, code, None
        R["공급처에 없는 상품 (전체 품절)"].append(f"[{brand}] {code}  {name}")
        return brand, code, {c["id"]: 0 for c in combos}

    names = group_names(oi)
    size_idx = next((i for i, n in enumerate(names) if "사이즈" in n), None)
    color_idx = next((i for i, n in enumerate(names) if "사이즈" not in n), None)
    colors_all = ", ".join(sorted({str(s["color"]) for s in skus}))
    color_cache = {}
    new = {}
    for c in combos:
        vals = [c.get("optionName1"), c.get("optionName2"), c.get("optionName3")]
        ko = vals[color_idx] if color_idx is not None else None
        sz = vals[size_idx] if size_idx is not None else None
        en, ok = None, True
        if ko is not None:
            if ko not in color_cache:
                en_c, guess = S.find_color(skus, ko, allow_guess=(brand != S.BRAND_DK),
                                           allow_single=not is_oz, code=code)
                if en_c is None:
                    R["공급처에 없는 색상 (품절)"].append(f"[{brand}] {code}  '{ko}'  (공급처 색상: {colors_all})")
                elif guess:
                    R["추정 매칭 색상 (확인 권장)"].append(f"{code}  '{ko}' -> {en_c}")
                color_cache[ko] = en_c
            en = color_cache[ko]
            ok = en is not None
        if not ok:
            new[c["id"]] = 0
            continue
        if sz is None:
            q = sum(x["stock"] for x in skus if en is None or x["color"] == en)
        else:
            q, found = S.size_stock(skus, en, sz, oz=is_oz, code=code)
            if not found and c.get("usable"):
                R["공급처에 없는 사이즈 (품절)"].append(f"[{brand}] {code}  '{ko or ''}/{sz}'")
        new[c["id"]] = S.final_qty(q)
    return brand, code, new


def build_body(d, new):
    """현재 값은 그대로 두고 재고만 바꾼 요청"""
    o = origin(d)
    oi = opt_info(d)
    combos = []
    for c in oi.get("optionCombinations") or []:
        item = {k: c[k] for k in ("id", "optionName1", "optionName2", "optionName3", "price",
                                  "sellerManagerCode", "usable") if k in c and c[k] is not None}
        item["stockQuantity"] = new.get(c["id"], int(c.get("stockQuantity") or 0))
        combos.append(item)
    body = {"productSalePrice": {"salePrice": o.get("salePrice")},
            "optionInfo": {"optionCombinations": combos}}
    if "useStockManagement" in oi:
        body["optionInfo"]["useStockManagement"] = oi["useStockManagement"]
    disc = discount_policy(d)
    if disc:
        body["immediateDiscountPolicy"] = disc
    return body


# ================================================================ 메인
def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("SYDNEY_CLIENT_ID / SYDNEY_CLIENT_SECRET 시크릿이 없습니다.")
    if MODE not in ("dry-run", "test-one", "apply"):
        sys.exit(f"MODE 값이 잘못됐습니다: {MODE}")
    print(f"모드: {MODE}")
    nv = Naver()
    nv.token()
    items = nv.list_products()
    print(f"시드니셀러 상품 {len(items)}개")

    # 대상 상품 고르기 (판매중·품절 상태)
    targets = []
    for it in items:
        chs = it.get("channelProducts") or []
        st = {ch.get("statusType") for ch in chs}
        if st & KEEP_STATUS:
            targets.append(it.get("originProductNo"))
    print(f"처리 대상(판매중·품절): {len(targets)}개")

    # 공급처 재고 (4개 브랜드 모두)
    sup = S.build_supplier({S.BRAND_DK, S.BRAND_EU, S.BRAND_OW, S.BRAND_OL})
    for b in list(sup):
        if not sup[b]:
            print(f"⚠️ {b}: 공급처 재고를 못 가져와서 이 브랜드는 건너뜀")
            del sup[b]

    R = collections.defaultdict(list)
    plans = []  # (brand, code, origin_no, detail, new, changes)
    zero_new = collections.Counter()
    opt_total = collections.Counter()
    for i, no in enumerate(targets, 1):
        d, err = nv.get(no)
        time.sleep(SLEEP)
        if d is None:
            R["상세 조회 실패 (건너뜀)"].append(f"{no}  {err}")
            continue
        brand, code, new = plan_product(d, sup, R)
        if new is None:
            if brand not in sup:
                R["다른 브랜드 (건너뜀)"].append(f"{brand or '-'}  {origin(d).get('name')}")
            continue
        cur = stocks_of(d)
        changes = [(oid, cur.get(oid, 0), q) for oid, q in new.items() if cur.get(oid, 0) != q]
        opt_total[brand] += len(new)
        zero_new[brand] += sum(1 for oid, old, q in changes if q == 0 and old > 0)
        if changes:
            plans.append((brand, code, no, d, new, changes))
        if i % 100 == 0:
            print(f"  {i}/{len(targets)} 확인")

    # 공급처 이상 감지: 브랜드별 품절 전환 비율
    skip_brands = set()
    for b, n in opt_total.items():
        if n and zero_new[b] / n > MAX_ZERO_RATIO:
            skip_brands.add(b)
            R["⚠️ 공급처 이상 의심으로 건너뛴 브랜드"].append(
                f"{b}: 옵션 {n}개 중 {zero_new[b]}개가 품절로 바뀔 예정 ({zero_new[b] / n:.0%}) -> 이번엔 바꾸지 않음")
    plans = [p for p in plans if p[0] not in skip_brands]

    # 바꿀 예정 목록
    def opt_label(d, oid):
        for c in opt_info(d).get("optionCombinations") or []:
            if c.get("id") == oid:
                return "/".join(str(c.get(k)) for k in ("optionName1", "optionName2", "optionName3") if c.get(k))
        return str(oid)

    for brand, code, no, d, new, changes in plans:
        parts = ", ".join(f"{opt_label(d, oid)} {old}→{q}" for oid, old, q in changes[:12])
        more = f" 외 {len(changes) - 12}개" if len(changes) > 12 else ""
        R["재고 변경 예정" if MODE == "dry-run" else "재고 변경 대상"].append(
            f"[{brand}] {code}  {origin(d).get('name')}\n      {parts}{more}")

    # 실제 적용
    done, failed = 0, 0
    if MODE in ("test-one", "apply") and plans:
        if MODE == "test-one":
            # 첫 시험은 할인 설정이 없는 상품으로 (할인 값 처리를 확인하기 전까지)
            plain = [p for p in plans if not discount_policy(p[3])]
            todo = (plain or plans)[:1]
        else:
            todo = plans
        for brand, code, no, d, new, changes in todo:
            before = snapshot(d)
            r = nv.put_option_stock(no, build_body(d, new))
            time.sleep(SLEEP)
            if r is None or r.status_code not in (200, 204):
                failed += 1
                R["❌ 변경 실패"].append(f"[{brand}] {code}  HTTP {getattr(r, 'status_code', '?')} "
                                       f"{getattr(r, 'text', '')[:400]}")
                if failed >= 5:
                    R["❌ 변경 실패"].append("실패가 5건이라 중단함")
                    break
                continue
            after_d, err = nv.get(no)
            time.sleep(SLEEP)
            if after_d is None:
                R["❌ 변경 후 확인 실패"].append(f"[{brand}] {code}  {err}")
                break
            after = snapshot(after_d)
            if after != before:
                diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
                R["❌ 재고 말고 다른 값이 바뀜 -> 즉시 중단"].append(
                    f"[{brand}] {code} (원상품 {no})\n      {json.dumps(diff, ensure_ascii=False)[:1500]}")
                break
            got = stocks_of(after_d)
            wrong = [(oid, q, got.get(oid)) for oid, q in new.items() if got.get(oid) != q]
            if wrong:
                R["⚠️ 재고가 예상과 다름"].append(f"[{brand}] {code}  {wrong[:5]}")
            done += 1
            R["✅ 변경 완료"].append(f"[{brand}] {code}  옵션 {len(changes)}개")

    # 보고서
    order = ["❌ 재고 말고 다른 값이 바뀜 -> 즉시 중단", "❌ 변경 실패", "❌ 변경 후 확인 실패", "⚠️ 재고가 예상과 다름",
             "⚠️ 공급처 이상 의심으로 건너뛴 브랜드", "✅ 변경 완료", "재고 변경 예정", "재고 변경 대상",
             "공급처에 없는 상품 (전체 품절)", "공급처에 없는 색상 (품절)", "공급처에 없는 사이즈 (품절)",
             "추정 매칭 색상 (확인 권장)", "에버어그 재고 API엔 없지만 가격표에 있는 상품 (재고 유지)",
             "오즈 공급처에 없는 상품 (재고 유지)",
             "건너뜀: 옵션 없음 (재고 유지)", "건너뜀: 단독형 옵션 (재고 유지)", "건너뜀: 간편 입력 옵션 (재고 유지)",
             "상세 조회 실패 (건너뜀)", "다른 브랜드 (건너뜀)"]
    order += [k for k in R if k not in order]
    summary = [f"모드: {MODE}", f"시드니셀러 상품: {len(items)}  (처리 대상 {len(targets)})",
               f"재고가 바뀌는 상품: {len(plans)}개 / 옵션 {sum(len(p[5]) for p in plans)}개",
               f"브랜드별: " + ", ".join(f"{b} {sum(1 for p in plans if p[0] == b)}" for b in
                                     (S.BRAND_DK, S.BRAND_EU, S.BRAND_OW, S.BRAND_OL)),
               f"그중 즉시할인 설정된 상품: {sum(1 for p in plans if discount_policy(p[3]))}개"]
    if MODE != "dry-run":
        summary.append(f"실제 변경: 성공 {done} / 실패 {failed}")
    summary += [f"⚠️ {n}" for n in S.SUPPLIER_NOTES]
    summary += [f"{k}: {len(R[k])}" for k in order if R[k]]
    body = []
    for k in order:
        if R[k]:
            body.append(f"\n■ {k} ({len(R[k])})")
            body += ["  " + x for x in R[k]]
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(summary) + "\n" + "\n".join(body) + "\n")
    print("\n" + "\n".join(summary))
    # 상세 내용도 실행 기록에 남김 (보고서 파일을 내려받지 않아도 확인 가능)
    print("\n========== 상세 보고서 ==========")
    print("\n".join(body))
    stop_keys = [k for k in order[:3] if R[k]]
    if stop_keys:
        print("\n".join(R[stop_keys[0]][:5]))
        sys.exit(1)


if __name__ == "__main__":
    main()
