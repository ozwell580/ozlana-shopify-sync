"""
11번가 재고 업로드 파일 만들기 (마켓오세아니아 11번가 / 해외사업자 - 엑셀 일괄수정 방식)
------------------------------------------------------------------------------------
공급처 재고(DK UGG / 에버어그 / 오즈웨어 / 오즈라나)를 읽어서
11번가 셀러오피스 '일괄수정(옵션/재고)' 양식으로 업로드 파일을 만듭니다.
공급처 조회와 색상·사이즈 맞추기 규칙은 smartstore_stock_sync.py 를 그대로 씁니다.

준비
  forms_11st/ 폴더에 11번가 셀러오피스에서 내려받은 일괄수정 엑셀을 넣어 둡니다.
  (상품번호 / 상품명 / 판매기간 / 판매가 / 기본즉시할인 / 옵션값 / 옵션가격 / 옵션재고수량 / 재고수량)
  여러 파일이어도 됩니다. 같은 상품번호가 여러 번 나오면 파일 이름 순서상 뒤의 것을 씀.
  ※ 판매가·옵션가격·즉시할인은 이 기준 파일 값을 그대로 다시 올리므로,
    11번가에서 가격을 바꿨다면 기준 파일도 새로 내려받아 바꿔 넣어야 합니다.

안전장치
  - 재고가 바뀌는 상품만 업로드 파일에 넣음 (가격·옵션값은 기준 파일 그대로)
  - 공급처 조회가 실패한 브랜드는 건너뜀
  - 한 브랜드에서 품절(0)로 바뀌는 옵션이 너무 많으면(기본 50% 초과) 그 브랜드는 건너뜀
  - 오즈웨어·오즈라나는 공급처에서 상품을 못 찾으면 재고 유지
  - 에버어그는 재고 API에 없어도 가격표(everugg_models.txt)에 있으면 재고 유지

출력
  11st_stock_upload_1.xlsx, _2 ...  : 업로드 파일 (UPLOAD_LIMIT 개씩)
  11st_stock_test1.xlsx             : 처음 시험용 (색상이 2개 이상인 상품 1개)
  11st_stock_report.txt             : 보고서
"""

import collections
import glob
import os
import re
import sys

import openpyxl

import smartstore_stock_sync as S

FORMS_DIR = os.environ.get("FORMS_11ST_DIR", "forms_11st")
OUT_PREFIX = "11st_stock"
REPORT_FILE = f"{OUT_PREFIX}_report.txt"
UPLOAD_LIMIT = int(os.environ.get("UPLOAD_LIMIT_11ST", "300"))
MAX_ZERO_RATIO = float(os.environ.get("MAX_ZERO_RATIO", "0.5"))
ONLY_CODES = {c.strip().upper() for c in os.environ.get("ONLY_CODES", "").split(",") if c.strip()}

HEAD = ["상품번호(수정불가)", "상품명", "판매기간", "판매가", "기본즉시할인",
        "옵션값(수정불가)", "옵션가격", "옵션재고수량", "재고수량"]
SINGLE = "__single__"


def load_everugg_models(path="everugg_models.txt"):
    try:
        with open(path, encoding="utf-8") as f:
            return {l.strip().upper() for l in f if l.strip() and not l.startswith("#")}
    except FileNotFoundError:
        print(f"⚠️ {path} 없음: 에버어그 가격표 기준을 쓰지 못함")
        return set()


EVERUGG_MODELS = load_everugg_models()


def lines(v):
    s = "" if v is None else str(v)
    s = s.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return s.split("\n") if s else []


def to_int(v):
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


# ================================================================ 기준 파일 읽기
def read_forms():
    files = sorted(glob.glob(os.path.join(FORMS_DIR, "*.xlsx")))
    if not files:
        sys.exit(f"{FORMS_DIR}/ 폴더에 11번가 일괄수정 엑셀이 없습니다.")
    prods = {}
    for fp in files:
        ws = openpyxl.load_workbook(fp, data_only=True).worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        hi = next((i for i, r in enumerate(rows[:10]) if r and str(r[0] or "").startswith("상품번호")), None)
        if hi is None:
            print(f"⚠️ {fp}: 머리글(상품번호...)을 못 찾아서 건너뜀")
            continue
        head = [str(h or "").strip() for h in rows[hi]]
        idx = {h: head.index(h) for h in HEAD if h in head}
        miss = [h for h in HEAD if h not in idx]
        if miss:
            print(f"⚠️ {fp}: 칸이 없음 {miss} -> 건너뜀")
            continue
        n = 0
        for r in rows[hi + 1:]:
            no = str(r[idx["상품번호(수정불가)"]] or "").strip()
            if not re.fullmatch(r"\d{6,}", no):
                continue  # 안내행 등
            prods[no] = {h: r[idx[h]] for h in HEAD}
            n += 1
        print(f"{fp}: 상품 {n}개")
    return prods


# ================================================================ 상품 판단
def code_of(name):
    found = S.CODE_RE.findall(str(name or "").upper())
    return found[-1].upper() if found else ""


def brand_of(name, code):
    n = re.sub(r"에버\s+어그", "에버어그", str(name or ""))
    n = re.sub(r"오즈\s+웨어", "오즈웨어", n)
    n = re.sub(r"오즈\s+라나", "오즈라나", n)
    b = S.brand_of(("", n, code), {"브랜드": 0, "상품명": 1, "판매자 상품코드": 2})
    if b in (S.BRAND_DK, S.BRAND_EU, S.BRAND_OW, S.BRAND_OL):
        return b
    if re.fullmatch(r"AS[A-Z]?\d+[A-Z]*", code):
        return S.BRAND_EU
    return None


def looks_size(v):
    s = str(v or "").strip().upper().replace(" ", "")
    if S.is_size_label(s):
        return True
    return bool(re.search(r"\d", s)) or s in ("FREE", "프리", "원사이즈")


def split_option(opt):
    """'체스트넛,5L(EU35)' -> (색상, 사이즈)"""
    parts = [p.strip() for p in str(opt).split(",")]
    if len(parts) == 1:
        return (None, parts[0]) if looks_size(parts[0]) else (parts[0], None)
    return parts[0], parts[-1]


def plan(p, sup, R):
    """새 옵션재고 리스트 (옵션 순서 그대로) / 옵션 없으면 [합계] / None = 건드리지 않음"""
    return plan_opts(str(p["상품명"] or ""), lines(p["옵션값(수정불가)"]), sup, R)


def plan_opts(name, opts, sup, R, code=None):
    """name: 상품명, opts: 옵션값 리스트('색상,사이즈'), code: 판매자상품코드(없으면 상품명에서)"""
    code = (code or "").strip().upper() or code_of(name)
    brand = brand_of(name, code)
    tag = f"[{brand or '-'}] {code}  {name}"
    if brand not in sup:
        R["다른 브랜드·공급처 없음 (건너뜀)"].append(tag)
        return brand, code, None
    if ONLY_CODES and code not in ONLY_CODES:
        return brand, code, None
    if not code:
        R["상품명에서 상품코드를 못 찾음 (건너뜀)"].append(tag)
        return brand, code, None

    is_oz = brand in S.OZ_BRANDS
    skus = sup[brand].get(S.OZ_CODE_ALIAS.get(code, code))
    if not skus:
        if is_oz:
            R["오즈 공급처에 없는 상품 (재고 유지)"].append(tag)
            return brand, code, None
        if brand == S.BRAND_EU and code in EVERUGG_MODELS:
            R["에버어그 재고 API엔 없지만 가격표에 있는 상품 (재고 유지)"].append(tag)
            return brand, code, None
        R["공급처에 없는 상품 (전체 품절)"].append(tag)
        return brand, code, [0] * len(opts) if opts else [0]

    if not opts:
        colors = sorted({str(s["color"]) for s in skus})
        if len(colors) > 1:
            R["옵션 없는 상품인데 공급처 색상이 여러 개 (합계로 반영, 확인 권장)"].append(
                f"{tag}  (공급처 색상: {', '.join(colors)})")
        return brand, code, [S.final_qty(sum(s["stock"] for s in skus))]

    colors_all = ", ".join(sorted({str(s["color"]) for s in skus}))
    color_cache = {}
    new = []
    sized, missing = 0, []  # 사이즈가 있는 옵션 수 / 공급처에서 사이즈를 못 찾은 옵션
    for opt in opts:
        ko, sz = split_option(opt)
        en = None
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
            if en is None:
                new.append(0)
                continue
        if sz is None:
            q = sum(x["stock"] for x in skus if en is None or x["color"] == en)
        else:
            sized += 1
            q, found = S.size_stock(skus, en, sz, oz=is_oz, code=code)
            if not found:
                missing.append((opt, en))
        new.append(S.final_qty(q))

    def sup_sizes(en):
        """공급처 원래 사이즈 표기 (오즈웨어는 raw_size, 그 외는 size)"""
        vals = [str(x.get("raw_size") or x["size"]) for x in skus if en is None or x["color"] == en]
        return ", ".join(dict.fromkeys(vals)) or "-"

    # 사이즈가 하나도 안 맞으면 품절이 아니라 '표기 차이'일 가능성이 큼 -> 0 으로 덮어쓰지 않고 재고 유지
    if sized >= 2 and len(missing) == sized:
        R["사이즈 표기가 하나도 안 맞음 (재고 유지, 확인 필요)"].append(
            f"{tag}\n      11번가: {', '.join(o for o, _ in missing)}\n      공급처: {sup_sizes(missing[0][1])}")
        return brand, code, None
    for opt, en in missing:
        R["공급처에 없는 사이즈 (품절)"].append(f"[{brand}] {code}  '{opt}'  (공급처 사이즈: {sup_sizes(en)})")
    return brand, code, new


# ================================================================ 파일 쓰기
def row_for(no, p, new):
    opts = lines(p["옵션값(수정불가)"])
    if opts:
        prices = lines(p["옵션가격"])
        if len(prices) != len(opts):
            prices = (prices + ["0"] * len(opts))[:len(opts)]
        opt_stock = "\n".join(str(q) for q in new)
        total = sum(new)
    else:
        prices, opt_stock, total = [], "", new[0]
    disc = p["기본즉시할인"]
    return [int(no), p["상품명"], "", to_int(p["판매가"]),
            "" if disc in (None, "-") else disc,
            "\n".join(opts), "\n".join(prices), opt_stock, total]


def write_file(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    wrap = openpyxl.styles.Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = wrap
    for col, w in zip("ABCDEFGHI", (14, 50, 8, 10, 10, 28, 10, 12, 10)):
        ws.column_dimensions[col].width = w
    wb.save(path)


# ================================================================ 메인
def main():
    prods = read_forms()
    print(f"11번가 기준 상품 {len(prods)}개")
    for old in glob.glob(f"{OUT_PREFIX}_upload_*.xlsx") + glob.glob(f"{OUT_PREFIX}_test1.xlsx"):
        os.remove(old)

    sup = S.build_supplier({S.BRAND_DK, S.BRAND_EU, S.BRAND_OW, S.BRAND_OL})
    for b in list(sup):
        if not sup[b]:
            print(f"⚠️ {b}: 공급처 재고를 못 가져와서 이 브랜드는 건너뜀")
            del sup[b]

    R = collections.defaultdict(list)
    plans = []  # (brand, code, no, p, new, changes)
    zero_new = collections.Counter()
    opt_total = collections.Counter()
    for no, p in prods.items():
        brand, code, new = plan(p, sup, R)
        if new is None:
            continue
        opts = lines(p["옵션값(수정불가)"])
        cur = [to_int(x) for x in lines(p["옵션재고수량"])] if opts else [to_int(p["재고수량"])]
        if len(cur) != len(new):
            cur = (cur + [None] * len(new))[:len(new)]
        labels = opts or ["상품재고"]
        changes = [(labels[i], cur[i], q) for i, q in enumerate(new) if cur[i] != q]
        opt_total[brand] += len(new)
        zero_new[brand] += sum(1 for _, old, q in changes if q == 0 and (old or 0) > 0)
        if changes:
            plans.append((brand, code, no, p, new, changes))

    skip = set()
    for b, n in opt_total.items():
        if n and zero_new[b] / n > MAX_ZERO_RATIO:
            skip.add(b)
            R["⚠️ 공급처 이상 의심으로 건너뛴 브랜드"].append(
                f"{b}: 옵션 {n}개 중 {zero_new[b]}개가 품절로 바뀔 예정 ({zero_new[b] / n:.0%}) -> 이번엔 파일에 넣지 않음")
    plans = [x for x in plans if x[0] not in skip]

    for brand, code, no, p, new, changes in plans:
        parts = ", ".join(f"{lab} {old}→{q}" for lab, old, q in changes[:12])
        more = f" 외 {len(changes) - 12}개" if len(changes) > 12 else ""
        R["재고 변경 (업로드 파일에 들어감)"].append(f"[{brand}] {code}  {no}  {p['상품명']}\n      {parts}{more}")

    rows = [row_for(no, p, new) for brand, code, no, p, new, changes in plans]
    files = []
    for i in range(0, len(rows), UPLOAD_LIMIT):
        fp = f"{OUT_PREFIX}_upload_{i // UPLOAD_LIMIT + 1}.xlsx"
        write_file(fp, rows[i:i + UPLOAD_LIMIT])
        files.append(fp)

    # 처음 시험용: 색상이 2개 이상이고 재고가 사이즈마다 다른 상품 1개
    test = None
    for x in plans:
        opts = lines(x[3]["옵션값(수정불가)"])
        if len({split_option(o)[0] for o in opts}) >= 2 and len(set(x[4])) >= 2:
            test = x
            break
    test = test or (plans[0] if plans else None)
    if test:
        write_file(f"{OUT_PREFIX}_test1.xlsx", [row_for(test[2], test[3], test[4])])
        R["시험용 파일 상품 (11st_stock_test1.xlsx)"].append(
            f"{test[2]}  {test[3]['상품명']}\n      " +
            "\n      ".join(f"{o} -> {q}" for o, q in zip(lines(test[3]['옵션값(수정불가)']) or ['상품재고'], test[4])))

    order = ["⚠️ 공급처 이상 의심으로 건너뛴 브랜드", "시험용 파일 상품 (11st_stock_test1.xlsx)",
             "재고 변경 (업로드 파일에 들어감)", "공급처에 없는 상품 (전체 품절)", "공급처에 없는 색상 (품절)",
             "공급처에 없는 사이즈 (품절)", "옵션 없는 상품인데 공급처 색상이 여러 개 (합계로 반영, 확인 권장)",
             "추정 매칭 색상 (확인 권장)", "에버어그 재고 API엔 없지만 가격표에 있는 상품 (재고 유지)",
             "오즈 공급처에 없는 상품 (재고 유지)", "상품명에서 상품코드를 못 찾음 (건너뜀)",
             "다른 브랜드·공급처 없음 (건너뜀)"]
    order += [k for k in R if k not in order]
    summary = [f"11번가 기준 상품: {len(prods)}개",
               f"재고가 바뀌는 상품: {len(plans)}개 / 옵션 {sum(len(x[5]) for x in plans)}개",
               "브랜드별: " + ", ".join(f"{b} {sum(1 for x in plans if x[0] == b)}"
                                     for b in (S.BRAND_DK, S.BRAND_EU, S.BRAND_OW, S.BRAND_OL)),
               f"업로드 파일: {', '.join(files) if files else '없음 (바뀔 재고 없음)'}"]
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
    print("\n========== 상세 보고서 ==========")
    print("\n".join(body))


if __name__ == "__main__":
    main()
