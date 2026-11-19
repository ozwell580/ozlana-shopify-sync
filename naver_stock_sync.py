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
  - 옵션 없는 상품이 품절 상태면 판매중으로 보내서 재고 반영 (품절 상태값은 네이버가 거부함)
  - 조합형 옵션 상품은 옵션별 재고를 갱신
  - 옵션 없는 상품·간편 입력 옵션 상품은 INCLUDE_SINGLE=on 일 때 '상품 재고'를 갱신
    (공급처 같은 상품코드의 재고 합계, 규칙은 엑셀 방식의 '설정안함'과 같음). 단독형 옵션은 보고서에만 표시

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
INCLUDE_SINGLE = (os.environ.get("INCLUDE_SINGLE") or "off").strip().lower() in ("on", "true", "1", "yes")
SINGLE = "상품재고"  # 옵션 없는 상품의 재고 키
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

# ---------------------------------------------------------------- 추가 매칭 규칙
# 한글 색상명 -> 공급처 영문 색상 (smartstore_stock_sync.py 변환표에 없는 것 보충)
#   공급처 그 상품에 그 영문 색상이 실제로 있을 때만 맞춤
COLOR_EXTRA = {
    "더스티로즈": "DUSTY ROSE",
    "퍼플": "PURPLE",
    "타로": "TARO",
    "로즈": "ROSE",
    "히비스커스": "HIBISCUS",
}

# 상품코드별로 확인 끝난 색상 매칭 (추정 매칭 -> 확정)
CODE_COLOR_FIX = {
    ("OB114II", "브라운"): "ROSY BROWN",
    ("OZ7012", "실버"): "SILVERY",
    ("OZ5021", "카멜"): "CHOCOLATE/CAMEL",
    ("OZ5021", "초콜릿"): "CHOCOLATE/CAMEL",
    ("AS8003", "프라신그린"): "Prasine Check",
}

# 스마트스토어 브랜드 표기가 달라도 이 브랜드로 연동
BRAND_OVERRIDE = {
    "OZ3035": S.BRAND_OL,  # 스토어 브랜드가 '어그'로 되어 있음 -> 오즈라나
}

# 상품 수정 때 네이버가 받지 않는 판매상태 (네이버가 재고에 따라 자동으로 정함)
AUTO_STATUS = {"OUTOFSTOCK"}


def _norm(s):
    return re.sub(r"[\s_\-]+", "", str(s)).upper()


def match_color(skus, ko, code):
    """추가 규칙으로 공급처 색상 찾기. 못 찾으면 None (기존 변환표로 넘어감)"""
    want = CODE_COLOR_FIX.get((code, ko)) or COLOR_EXTRA.get(str(ko).replace(" ", ""))
    if not want:
        return None
    for s in skus:
        if _norm(s["color"]) == _norm(want):
            return s["color"]
    return None


def mens_size_fallback(skus, en, sz):
    """오즈웨어 남성 사이즈 보충: 스토어 '남성AU9' <-> 공급처 '42(9M)'
    기존 규칙으로 못 찾은 경우에만 씀. 반환 (재고, 찾음여부)"""
    m = re.search(r"AU\s*(\d+)", str(sz), re.I)
    if not m or "남성" not in str(sz):
        return 0, False
    pat = re.compile(r"\(\s*%s\s*M\s*\)" % m.group(1), re.I)
    q, found = 0, False
    for x in skus:
        if en is not None and x["color"] != en:
            continue
        if any(isinstance(v, str) and pat.search(v) for k, v in x.items() if k != "color"):
            q += int(x.get("stock") or 0)
            found = True
    return q, found


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

    def put_product(self, origin_no, body):
        """원상품 전체 수정 (옵션 없는 상품의 재고는 이 방식으로만 바꿀 수 있음)"""
        return self.call("PUT", f"/v2/products/origin-products/{origin_no}", body)


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
        "simple": sorted(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in oi.get("optionSimple") or []),
        "standards": sorted(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in oi.get("optionStandards") or []),
        "name": o.get("name"),
    }


def stocks_of(d):
    combos = opt_info(d).get("optionCombinations") or []
    if not combos:
        return {SINGLE: int(origin(d).get("stockQuantity") or 0)}
    return {c.get("id"): int(c.get("stockQuantity") or 0) for c in combos}


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
    if code in BRAND_OVERRIDE:
        brand = BRAND_OVERRIDE[code]
    if brand not in sup:
        return brand, code, None
    if ONLY_CODES and code not in ONLY_CODES:
        return brand, code, None
    oi = opt_info(d)
    combos = oi.get("optionCombinations") or []
    if not combos:
        kind = "간편 입력 옵션" if oi.get("optionSimple") else ("단독형 옵션" if oi.get("optionStandards") else "옵션 없음")
        if kind == "단독형 옵션" or not INCLUDE_SINGLE:
            R[f"건너뜀: {kind} (재고 유지)"].append(f"[{brand}] {code}  {name}")
            return brand, code, None
        return brand, code, plan_single(brand, code, name, kind, sup, R)

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
                en_c, guess = match_color(skus, ko, code), False
                if en_c is None:
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
            if not found and is_oz:
                q2, found2 = mens_size_fallback(skus, en, sz)
                if found2:
                    q, found = q2, True
            if not found and c.get("usable"):
                R["공급처에 없는 사이즈 (품절)"].append(f"[{brand}] {code}  '{ko or ''}/{sz}'")
        new[c["id"]] = S.final_qty(q)
    return brand, code, new


def plan_single(brand, code, name, kind, sup, R):
    """옵션 없는 상품(간편 입력 옵션 포함): 공급처 같은 상품코드 재고 합계를 상품 재고로"""
    is_oz = brand in S.OZ_BRANDS
    skus = sup[brand].get(S.OZ_CODE_ALIAS.get(code, code))
    if not skus:
        if is_oz:
            R["오즈 공급처에 없는 상품 (재고 유지)"].append(f"[{brand}] {code}  {name}")
            return None
        if brand == S.BRAND_EU and code in EVERUGG_MODELS:
            R["에버어그 재고 API엔 없지만 가격표에 있는 상품 (재고 유지)"].append(f"[{brand}] {code}  {name}")
            return None
        R["공급처에 없는 상품 (전체 품절)"].append(f"[{brand}] {code}  {name}")
        return {SINGLE: 0}
    colors = sorted({str(s["color"]) for s in skus})
    if len(colors) > 1:
        R["옵션 없는 상품인데 공급처 색상이 여러 개 (합계로 반영, 확인 권장)"].append(
            f"[{brand}] {code}  {name}  (공급처 색상: {', '.join(colors)})")
    R[f"옵션 없는 상품 재고 연동 ({kind})"].append(f"[{brand}] {code}  {name}")
    return {SINGLE: S.final_qty(sum(s["stock"] for s in skus))}


def build_single_body(d, q):
    """옵션 없는 상품: 조회한 상품 정보 전체를 그대로 두고 상품 재고(stockQuantity)만 바꾼 요청.
    옵션 재고 API(option-stock)는 optionInfo가 꼭 있어야 해서 옵션 없는 상품엔 쓸 수 없음
    -> 원상품 전체 수정 API(PUT /v2/products/origin-products/{번호})로 보냄"""
    body = json.loads(json.dumps(d))  # 깊은 복사
    o = body["originProduct"]
    o["stockQuantity"] = q
    # 품절(OUTOFSTOCK)은 네이버가 자동으로 정하는 상태라 요청에 넣으면 400 오류가 남
    # -> 판매중(SALE)으로 보내면 재고 0이면 네이버가 다시 품절로, 1 이상이면 판매중으로 둠
    if o.get("statusType") in AUTO_STATUS:
        o["statusType"] = "SALE"
    return body


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
    print(f"모드: {MODE}  /  옵션 없는 상품 연동: {'켜짐' if INCLUDE_SINGLE else '꺼짐'}")
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
            # 옵션 없는 상품 연동을 켰으면 그 상품부터 시험
            pool = plans
            if INCLUDE_SINGLE and any(SINGLE in p[4] for p in plans):
                pool = [p for p in plans if SINGLE in p[4]]
            plain = [p for p in pool if not discount_policy(p[3])]
            todo = (plain or pool)[:1]
        else:
            todo = plans
        for brand, code, no, d, new, changes in todo:
            before = snapshot(d)
            if SINGLE in new:
                r = nv.put_product(no, build_single_body(d, new[SINGLE]))
            else:
                r = nv.put_option_stock(no, build_body(d, new))
            time.sleep(SLEEP)
            if r is None or r.status_code not in (200, 204):
                failed += 1
                R["❌ 변경 실패"].append(f"[{brand}] {code}  HTTP {getattr(r, 'status_code', '?')} "
                                       f"{getattr(r, 'text', '')[:400]}")
                if failed >= 5:
                    R["❌ 실패 5건이라 중단함"].append(f"실패 {failed}건에서 멈춤 - 나머지 상품은 바꾸지 않음")
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
    order = ["❌ 재고 말고 다른 값이 바뀜 -> 즉시 중단", "❌ 변경 실패", "❌ 변경 후 확인 실패", "❌ 실패 5건이라 중단함",
             "⚠️ 재고가 예상과 다름",
             "⚠️ 공급처 이상 의심으로 건너뛴 브랜드", "✅ 변경 완료", "재고 변경 예정", "재고 변경 대상",
             "공급처에 없는 상품 (전체 품절)", "공급처에 없는 색상 (품절)", "공급처에 없는 사이즈 (품절)",
             "옵션 없는 상품인데 공급처 색상이 여러 개 (합계로 반영, 확인 권장)",
             "추정 매칭 색상 (확인 권장)", "에버어그 재고 API엔 없지만 가격표에 있는 상품 (재고 유지)",
             "오즈 공급처에 없는 상품 (재고 유지)",
             "건너뜀: 옵션 없음 (재고 유지)", "건너뜀: 단독형 옵션 (재고 유지)", "건너뜀: 간편 입력 옵션 (재고 유지)",
             "상세 조회 실패 (건너뜀)", "다른 브랜드 (건너뜀)"]
    order += [k for k in R if k not in order]
    summary = [f"모드: {MODE}  /  옵션 없는 상품 연동: {'켜짐' if INCLUDE_SINGLE else '꺼짐'}", f"시드니셀러 상품: {len(items)}  (처리 대상 {len(targets)})",
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
