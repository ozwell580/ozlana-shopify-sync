"""
11번가 재고 자동 연동 (11번가 Open API)
------------------------------------------------
공급처 재고(DK UGG / 에버어그 / 오즈웨어 / 오즈라나)를 읽어서
11번가 상품의 '옵션별 재고'만 Open API로 갱신합니다. (가격·옵션·판매상태는 건드리지 않음)
공급처 조회와 색상·사이즈 맞추기 규칙은 smartstore_stock_sync.py 를 그대로 씁니다.

실행 모드 (환경변수 MODE)
  dry-run  : 바꾸지 않고 '바꿀 예정' 보고서만 만듦 (기본값)
  test-one : 바뀌는 상품 중 1개만 실제로 바꾸고, 다시 읽어서 확인
  apply    : 바뀌는 상품 전부 실제로 바꿈 (상품마다 바꾼 뒤 다시 읽어서 확인)

안전장치
  - 옵션 재고 숫자만 바꿈 (재고번호별 PUT)
  - 공급처 조회가 실패한 브랜드는 건너뜀
  - 한 브랜드에서 품절(0)로 바뀌는 옵션이 너무 많으면(기본 50% 초과) 그 브랜드는 건너뜀
  - 오즈웨어·오즈라나는 공급처에서 상품을 못 찾으면 재고 유지
  - 에버어그는 재고 API에 없어도 가격표(everugg_models.txt)에 있으면 재고 유지
  - 실패가 5건 쌓이면 중단

필요한 GitHub 시크릿
  ELEVEN_API_KEY, NAVER_PROXY(고정 IP 프록시, 11번가 상용서버 IP에 등록)
  + 공급처 시크릿 (EVERUGG_*, OZLANA_*, OZWEAR_*, SHOPIFY_*)
출력
  11st_api_report.txt
"""

import collections
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests

import smartstore_stock_sync as S
import eleven_stock_sync as E

API = "http://api.11st.co.kr/rest"
KEY = os.environ.get("ELEVEN_API_KEY", "").strip()
PROXY = os.environ.get("NAVER_PROXY", "").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None
MODE = (os.environ.get("MODE") or "dry-run").strip().lower()
MAX_ZERO_RATIO = float(os.environ.get("MAX_ZERO_RATIO", "0.5"))
ONLY_CODES = {c.strip().upper() for c in os.environ.get("ONLY_CODES", "").split(",") if c.strip()}
E.ONLY_CODES = ONLY_CODES
REPORT_FILE = "11st_api_report.txt"
SLEEP = 0.2
STATUSES = {"103": "판매중", "104": "품절"}  # 판매중·품절 상품만 처리


def strip_ns(el):
    for e in el.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
        if isinstance(e.tag, str) and ":" in e.tag:
            e.tag = e.tag.split(":", 1)[1]
    return el


def parse(r):
    """11번가 응답은 euc-kr XML -> 글자로 바꾼 뒤 선언부를 떼고 읽음"""
    raw = r.content
    try:
        txt = raw.decode("euc-kr")
    except UnicodeDecodeError:
        txt = raw.decode("utf-8", errors="replace")
    if txt.lstrip().startswith("<?xml"):
        txt = txt.split("?>", 1)[1]
    return strip_ns(ET.fromstring(txt))


class Eleven:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"openapikey": KEY, "Content-Type": "text/xml; charset=euc-kr"})

    def req(self, method, path, body=None, tries=3):
        data = body.encode("euc-kr", errors="replace") if body else None
        last = None
        for i in range(tries):
            try:
                r = self.s.request(method, API + path, data=data, proxies=PROXIES, timeout=60)
                if r.status_code < 500:
                    return r
                last = r
            except requests.RequestException as e:
                last = e
            time.sleep(2 * (i + 1))
        if isinstance(last, Exception):
            raise last
        return last

    def list_products(self):
        out = {}
        for st in STATUSES:
            start = 1
            while True:
                end = start + 499
                body = (f'<?xml version="1.0" encoding="euc-kr"?><SearchProduct><selStatCd>{st}</selStatCd>'
                        f"<limit>500</limit><start>{start}</start><end>{end}</end></SearchProduct>")
                r = self.req("POST", "/prodmarketservice/prodmarket", body)
                if r.status_code != 200:
                    raise RuntimeError(f"상품 목록 조회 실패 HTTP {r.status_code}: {r.text[:300]}")
                root = parse(r)
                items = root.findall(".//product")
                if not items and start == 1:
                    msg = (root.findtext(".//message") or root.findtext(".//resultMessage") or "").strip()
                    if msg:
                        print(f"  {STATUSES[st]} 목록: {msg[:200]}")
                for p in items:
                    no = (p.findtext("prdNo") or "").strip()
                    if no:
                        out[no] = {"prdNo": no, "prdNm": p.findtext("prdNm") or "",
                                   "sellerPrdCd": p.findtext("sellerPrdCd") or "", "selStatCd": st}
                if len(items) < 500:
                    break
                start += 500
                time.sleep(SLEEP)
        return out

    def stocks(self, no):
        r = self.req("GET", f"/prodmarketservice/prodmarket/stck/{no}")
        if r.status_code != 200:
            return None, f"HTTP {r.status_code} {r.text[:200]}"
        root = parse(r)
        rows = []
        for s in root.iter("ProductStock"):
            if s.find("prdStckNo") is None:
                continue
            rows.append({k: (s.findtext(k) or "").strip() for k in
                         ("prdStckNo", "mixDtlOptNm", "mixOptNm", "stckQty", "optWght", "prdStckStatCd", "addPrc")})
        if not rows:
            msg = (root.findtext(".//message") or "").strip()
            return None, f"재고 정보 없음 {msg[:200]}"
        return rows, None

    def set_stock(self, no, row, qty):
        body = (f'<?xml version="1.0" encoding="euc-kr"?><ProductStock><prdNo>{no}</prdNo>'
                f'<prdStckNo>{row["prdStckNo"]}</prdStckNo><stckQty>{qty}</stckQty>'
                f'<optWght>{row.get("optWght") or 0}</optWght></ProductStock>')
        r = self.req("PUT", f"/prodservices/stockqty/{row['prdStckNo']}", body)
        code, msg = None, r.text[:300]
        try:
            root = parse(r)
            code = (root.findtext(".//resultCode") or "").strip()
            msg = (root.findtext(".//message") or msg).strip()
        except ET.ParseError:
            pass
        ok = r.status_code == 200 and code in ("200", "")
        return ok, f"HTTP {r.status_code} {code} {msg}"


def opt_list(rows):
    """옵션 없는 상품은 재고 행이 1개이고 옵션명이 비어 있음"""
    if len(rows) == 1 and not rows[0]["mixOptNm"]:
        return []
    return [r["mixDtlOptNm"] for r in rows]


def main():
    if not KEY:
        sys.exit("ELEVEN_API_KEY 시크릿이 없습니다.")
    if MODE not in ("dry-run", "test-one", "apply"):
        sys.exit(f"MODE 값이 잘못됐습니다: {MODE}")
    print(f"모드: {MODE}  /  프록시: {'사용' if PROXY else '없음'}")
    api = Eleven()
    prods = api.list_products()
    print(f"11번가 상품(판매중·품절): {len(prods)}개")

    sup = S.build_supplier({S.BRAND_DK, S.BRAND_EU, S.BRAND_OW, S.BRAND_OL})
    for b in list(sup):
        if not sup[b]:
            print(f"⚠️ {b}: 공급처 재고를 못 가져와서 이 브랜드는 건너뜀")
            del sup[b]

    R = collections.defaultdict(list)
    plans = []  # (brand, code, no, name, rows, changes[(row, old, new)])
    zero_new = collections.Counter()
    opt_total = collections.Counter()
    n = 0
    for no, p in prods.items():
        name = p["prdNm"]
        code0 = p["sellerPrdCd"]
        brand = E.brand_of(name, (code0 or E.code_of(name)).upper())
        if brand not in sup:
            R["다른 브랜드·공급처 없음 (건너뜀)"].append(f"[{brand or '-'}] {no}  {name}")
            continue
        if ONLY_CODES and (code0 or E.code_of(name)).upper() not in ONLY_CODES:
            continue
        rows, err = api.stocks(no)
        time.sleep(SLEEP)
        n += 1
        if n % 100 == 0:
            print(f"  {n}개 재고 조회")
        if rows is None:
            R["재고 조회 실패 (건너뜀)"].append(f"{no}  {name}  {err}")
            continue
        opts = opt_list(rows)
        brand, code, new = E.plan_opts(name, opts, sup, R, code=code0)
        if new is None:
            continue
        if len(new) != len(rows):
            R["옵션 개수가 맞지 않음 (건너뜀)"].append(f"[{brand}] {code}  {no}  {name}")
            continue
        changes = [(row, E.to_int(row["stckQty"]), q) for row, q in zip(rows, new)
                   if E.to_int(row["stckQty"]) != q]
        opt_total[brand] += len(new)
        zero_new[brand] += sum(1 for _, old, q in changes if q == 0 and old > 0)
        if changes:
            plans.append((brand, code, no, name, rows, changes))

    skip = set()
    for b, cnt in opt_total.items():
        if cnt and zero_new[b] / cnt > MAX_ZERO_RATIO:
            skip.add(b)
            R["⚠️ 공급처 이상 의심으로 건너뛴 브랜드"].append(
                f"{b}: 옵션 {cnt}개 중 {zero_new[b]}개가 품절로 바뀔 예정 ({zero_new[b] / cnt:.0%}) -> 이번엔 바꾸지 않음")
    plans = [x for x in plans if x[0] not in skip]

    def label(row):
        return row["mixDtlOptNm"] or "상품재고"

    for brand, code, no, name, rows, changes in plans:
        parts = ", ".join(f"{label(r)} {old}→{q}" for r, old, q in changes[:12])
        more = f" 외 {len(changes) - 12}개" if len(changes) > 12 else ""
        R["재고 변경 예정" if MODE == "dry-run" else "재고 변경 대상"].append(
            f"[{brand}] {code}  {no}  {name}\n      {parts}{more}")

    done, failed = 0, 0
    if MODE in ("test-one", "apply") and plans:
        todo = plans
        if MODE == "test-one":
            # 색상이 2개 이상이고 0으로 바뀌는 옵션이 있는 상품으로 시험 (순서·0 재고 둘 다 확인)
            pick = [x for x in plans if len({E.split_option(r["mixDtlOptNm"])[0] for r in x[4]}) >= 2
                    and any(q == 0 for _, _, q in x[5]) and any(q > 0 for _, _, q in x[5])]
            todo = (pick or plans)[:1]
        stop = False
        for brand, code, no, name, rows, changes in todo:
            bad = 0
            for row, old, q in changes:
                ok, msg = api.set_stock(no, row, q)
                time.sleep(SLEEP)
                if not ok:
                    bad += 1
                    failed += 1
                    R["❌ 변경 실패"].append(f"[{brand}] {code}  {no}  {label(row)} {old}→{q}  {msg}")
                    if failed >= 5:
                        R["❌ 변경 실패"].append("실패가 5건이라 중단함")
                        stop = True
                        break
            if stop:
                break
            after, err = api.stocks(no)
            time.sleep(SLEEP)
            if after is None:
                R["❌ 변경 후 확인 실패"].append(f"[{brand}] {code}  {no}  {err}")
                continue
            want = {r["prdStckNo"]: q for r, _, q in changes}
            got = {r["prdStckNo"]: E.to_int(r["stckQty"]) for r in after}
            wrong = [(k, v, got.get(k)) for k, v in want.items() if got.get(k) != v]
            if wrong:
                R["⚠️ 재고가 예상과 다름"].append(f"[{brand}] {code}  {no}  {wrong[:5]}")
            if not bad:
                done += 1
                R["✅ 변경 완료"].append(f"[{brand}] {code}  {no}  옵션 {len(changes)}개")
            if MODE == "test-one":
                R["시험 상품 결과 (11번가에서 확인)"].append(
                    f"{no}  {name}\n      " + "\n      ".join(
                        f"{r['mixDtlOptNm'] or '상품재고'} -> {r['stckQty']} (상태 {r['prdStckStatCd']})" for r in after))

    order = ["❌ 변경 실패", "❌ 변경 후 확인 실패", "⚠️ 재고가 예상과 다름", "⚠️ 공급처 이상 의심으로 건너뛴 브랜드",
             "시험 상품 결과 (11번가에서 확인)", "✅ 변경 완료", "재고 변경 예정", "재고 변경 대상",
             "공급처에 없는 상품 (전체 품절)", "공급처에 없는 색상 (품절)", "공급처에 없는 사이즈 (품절)",
             "옵션 없는 상품인데 공급처 색상이 여러 개 (합계로 반영, 확인 권장)", "추정 매칭 색상 (확인 권장)",
             "에버어그 재고 API엔 없지만 가격표에 있는 상품 (재고 유지)", "오즈 공급처에 없는 상품 (재고 유지)",
             "상품명에서 상품코드를 못 찾음 (건너뜀)", "옵션 개수가 맞지 않음 (건너뜀)", "재고 조회 실패 (건너뜀)",
             "다른 브랜드·공급처 없음 (건너뜀)"]
    order += [k for k in R if k not in order]
    summary = [f"모드: {MODE}", f"11번가 상품(판매중·품절): {len(prods)}  (재고 조회 {n})",
               f"재고가 바뀌는 상품: {len(plans)}개 / 옵션 {sum(len(x[5]) for x in plans)}개",
               "브랜드별: " + ", ".join(f"{b} {sum(1 for x in plans if x[0] == b)}"
                                     for b in (S.BRAND_DK, S.BRAND_EU, S.BRAND_OW, S.BRAND_OL))]
    if MODE != "dry-run":
        summary.append(f"실제 변경: 상품 성공 {done} / 옵션 실패 {failed}")
    summary += [f"⚠️ {x}" for x in S.SUPPLIER_NOTES]
    summary += [f"{k}: {len(R[k])}" for k in order if R[k]]
    body = []
    for k in order:
        if R[k]:
            body.append(f"\n■ {k} ({len(R[k])})")
            body += ["  " + x for x in R[k]]
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(summary) + "\n" + "\n".join(body) + "\n")
    print("\n" + "\n".join(summary))
    print("\n========== 상세 보고서 ==========")
    print("\n".join(body))
    if R["❌ 변경 실패"] or R["❌ 변경 후 확인 실패"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
