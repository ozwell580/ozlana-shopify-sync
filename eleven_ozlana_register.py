"""
11번가 오즈라나 상품 등록 (11번가 Open API)
------------------------------------------------
시드니셀러(네이버)에 올라간 오즈라나 상품을 11번가에 새로 등록합니다.
등록 설정은 11번가에 이미 올라간 오즈웨어 상품(OB890)과 똑같이 맞춥니다.

가격   : 11번가 판매가 = 시드니셀러 판매가 x 1.13 (100원 단위 올림)  ※ 기존 11번가 어그 상품과 같은 규칙
배송비 : 시드니셀러와 같은 금액, 상품 1개당 배송비, 선결제, 우체국택배, 반품 25,000 / 교환 50,000
이미지 : market-images 저장소 OZLANA/{코드}/{코드}_main_1.jpg
상세   : 시드니셀러 상세와 같은 이미지, 머리말·꼬리말만 마켓오세아니아용으로 바꿈
옵션   : 시드니셀러 옵션(색상·사이즈) 그대로, 품절 옵션도 모두 넣음 -> 등록 직후 공급처 재고로 바로 맞춤

실행 모드 (환경변수 MODE)
  dry-run  : 등록하지 않고 보고서·가격표만 만듦 (기본값)
  test-one : 1개만 등록 (ONLY_CODES 로 고를 수 있음)
  apply    : 아직 11번가에 없는 오즈라나 상품 전부 등록

필요한 GitHub 시크릿: ELEVEN_API_KEY, NAVER_PROXY, SYDNEY_CLIENT_ID, SYDNEY_CLIENT_SECRET, OZLANA_*
출력: 11st_ozlana_report.txt, 11st_ozlana_prices.csv
"""
import csv
import html
import math
import os
import re
import sys
import time

import requests

import naver_stock_sync as N
import eleven_api_stock_sync as A
import eleven_stock_sync as E
import smartstore_stock_sync as S
import ozlana_api

MODE = (os.environ.get("MODE") or "dry-run").strip().lower()
ONLY = {c.strip().upper() for c in os.environ.get("ONLY_CODES", "").split(",") if c.strip()}
PRICE_RATE = 1.13
FEE_11ST = 0.13          # 11번가 기본서비스이용율 (정산내역 기준)
FX = 1000                # 원가 계산용 환율 (보수적으로 1 AUD = 1,000원)
IMG = "https://cdn.jsdelivr.net/gh/ozwell580/market-images@main"
REPORT = "11st_ozlana_report.txt"
PRICES = "11st_ozlana_prices.csv"

# 네이버 카테고리 -> 11번가 카테고리 (기존 상품 대응표 + 의류 2개 직접 지정)
CTG = {
    "50004191": "10474", "50003834": "10474", "50004190": "10474",           # 부츠
    "50023939": "10475", "50023919": "10475", "50003847": "10475",           # 슬리퍼·플랫폼·뮬
    "50003818": "10471", "50003817": "10471", "50003820": "10471",           # 로퍼·플랫·모카신
    "50003840": "123517", "50023899": "123517",                              # 스니커즈·슬립온
    "50000639": "10503", "50000640": "10504", "50000641": "10506", "50000644": "10506",  # 가방
    "50000643": "943275", "50000570": "943273", "50000565": "123617",         # 파우치·키링·머플러
    "50021380": "957883",   # 무스탕 -> 해외직구>의류/언더웨어>여성아우터/재킷>가죽/FUR
    "50021441": "1020695",  # 베스트 -> 해외직구>의류/언더웨어>여성스웨터/카디건>베스트/조끼/판초
}
SHOES = {"10474", "10475", "10471", "123517"}
BAGS = {"10503", "10504", "10506", "943275"}
CLOTHES = {"957883", "1020695"}
NOTI = {  # 상품정보제공고시 유형 -> 항목코드 (전부 '상품상세설명 참조')
    "891011": ["11835", "23756520", "23759095", "23760437", "23759468", "23760034", "23760386", "11905", "23759308"],
    "891012": ["11835", "11905", "23759095", "40748371", "23760034", "23760386", "23760437", "23759972"],
    "891013": ["11835", "11848", "11905", "11908", "23760437", "23759095", "23759972", "23760386", "11932"],
    "891014": ["11848", "11905", "11908", "23760437", "23759972", "23760034", "23760386", "23759095"],
}
AS_DETAIL = ("해외구매대행 상품 특성상 국내 무상 A/S가 불가합니다. 상품 이상 시 수령 후 7일 이내 판매자에게 문의해 주세요. "
             "A/S 문의: 61466699900")
RTNG_DETAIL = ("톡톡으로 문의주시면 안내 도와드리겠습니다. 상품 청약철회 가능기간은 상품 수령일로부터 7일 이내입니다. "
               "상품 밀봉 또는 개봉(실링제거) 등으로 상품 가치 훼손 시에는 상품 청약철회 가능기간 이내라도 교환 및 반품이 불가능합니다. "
               "고객 변심에 의한 교환, 반품은 고객께서 왕복배송비를 부담하셔야 합니다. (제품의 하자, 배송오류는 제외)")
BAD_OPT = re.compile(r"[\[\]&#;\"%<>†]")


def noti_type(ctg):
    if ctg in SHOES:
        return "891012"
    if ctg in BAGS:
        return "891013"
    if ctg in CLOTHES:
        return "891011"
    return "891014"


def price11(sp):
    return int(math.ceil(sp * PRICE_RATE / 100.0) * 100)


def cdata(s):
    return "<![CDATA[" + str(s).replace("]]>", "]]]]><![CDATA[>") + "]]>"


def detail_html(d, code):
    o = d.get("originProduct") or {}
    h = o.get("detailContent") or ""
    h = h.replace("header_sydneyseller", "header_marketoceania").replace("footer_sydneyseller", "footer_marketoceania")
    h = h.replace("[시드니셀러]", "[마켓오세아니아]").replace("시드니셀러", "마켓오세아니아")
    if not h.strip():
        h = (f'<div style="text-align:center;"><img src="{IMG}/common/header_marketoceania.png" style="display:block;width:100%;max-width:860px;margin:0 auto;">'
             + "".join(f'<img src="{IMG}/OZLANA/{code}/{code}_detail_{i}.jpg" style="display:block;width:100%;max-width:860px;margin:0 auto;">'
                       for i in range(1, 7))
             + f'<img src="{IMG}/common/footer_marketoceania.png" style="display:block;width:100%;max-width:860px;margin:0 auto;"></div>')
    return h


def options_of(d):
    oi = N.opt_info(d)
    names = N.group_names(oi)
    combos = oi.get("optionCombinations") or []
    return names, combos


def build_xml(d, code, ctg, p11, fee, stock_total):
    o = d.get("originProduct") or {}
    name = (o.get("name") or "").strip()[:100]
    names, combos = options_of(d)
    nt = noti_type(ctg)
    x = ['<?xml version="1.0" encoding="euc-kr"?>', "<Product>",
         "<abrdBuyPlace>A</abrdBuyPlace>", "<abrdSizetableDispYn>Y</abrdSizetableDispYn>",
         "<selMnbdNckNm>" + cdata("마켓오세아니아") + "</selMnbdNckNm>",
         "<selMthdCd>01</selMthdCd>", f"<dispCtgrNo>{ctg}</dispCtgrNo>", "<prdTypCd>01</prdTypCd>",
         "<prdNm>" + cdata(name) + "</prdNm>", "<advrtStmt>" + cdata("호주 구매대행 마켓오세아니아") + "</advrtStmt>",
         "<brand>" + cdata("오즈라나") + "</brand>",
         "<rmaterialTypCd>04</rmaterialTypCd>", "<orgnTypCd>02</orgnTypCd>", "<orgnTypDtlsCd>1441</orgnTypDtlsCd>",
         f"<sellerPrdCd>{code}</sellerPrdCd>", "<suplDtyfrPrdClfCd>01</suplDtyfrPrdClfCd>",
         "<forAbrdBuyClf>01</forAbrdBuyClf>", "<importFeeCd>03</importFeeCd>",
         "<prdStatCd>01</prdStatCd>", "<minorSelCnYn>Y</minorSelCnYn>",
         f"<prdImage01>{IMG}/OZLANA/{code}/{code}_main_1.jpg</prdImage01>",
         "<htmlDetail>" + cdata(detail_html(d, code)) + "</htmlDetail>"]
    for g, obj in (("01", "03"), ("02", "03"), ("03", "03"), ("04", "05")):
        x.append(f"<ProductCertGroup><crtfGrpTypCd>{g}</crtfGrpTypCd><crtfGrpObjClfCd>{obj}</crtfGrpObjClfCd></ProductCertGroup>")
    x += ["<reviewDispYn>Y</reviewDispYn>", "<selPrdClfCd>3y:110</selPrdClfCd>",
          f"<selPrc>{p11}</selPrc>"]
    if combos:
        x += ["<optSelectYn>Y</optSelectYn>", "<txtColCnt>1</txtColCnt>",
              f"<optionAllQty>{max(1, stock_total)}</optionAllQty>", "<optionAllAddPrc>0</optionAllAddPrc>",
              "<optionAllAddWght>0</optionAllAddWght>", "<prdExposeClfCd>00</prdExposeClfCd>"]
        for gi, gname in enumerate(names, 1):
            vals = []
            for c in combos:
                v = c.get(f"optionName{gi}")
                if v and v not in vals:
                    vals.append(v)
            title = "색상" if "사이즈" not in gname else "사이즈"
            x.append("<ProductRootOption>" + "<colTitle>" + cdata(title) + "</colTitle>" + "".join(
                "<ProductOption><colOptPrice>0</colOptPrice><colValue0>" + cdata(v) + "</colValue0></ProductOption>"
                for v in vals) + "</ProductRootOption>")
    x.append(f"<prdSelQty>{max(1, stock_total)}</prdSelQty>")
    x += ["<gftPackTypCd>01</gftPackTypCd>", "<dlvCnAreaCd>01</dlvCnAreaCd>", "<dlvWyCd>01</dlvWyCd>",
          "<dlvEtprsCd>00007</dlvEtprsCd>", "<dlvCstInstBasiCd>05</dlvCstInstBasiCd>",
          f"<dlvCst1>{fee}</dlvCst1>", f"<dlvCst4>{fee}</dlvCst4>", "<dlvCnt1>1</dlvCnt1>",
          "<bndlDlvCnYn>N</bndlDlvCnYn>", "<dlvCstPayTypCd>03</dlvCstPayTypCd>",
          "<jejuDlvCst>0</jejuDlvCst>", "<islandDlvCst>0</islandDlvCst>",
          "<addrSeqOut>2</addrSeqOut>", "<addrSeqIn>3</addrSeqIn>",
          "<rtngdDlvCst>25000</rtngdDlvCst>", "<exchDlvCst>50000</exchDlvCst>", "<rtngdDlvCd>01</rtngdDlvCd>",
          "<asDetail>" + cdata(AS_DETAIL) + "</asDetail>", "<rtngExchDetail>" + cdata(RTNG_DETAIL) + "</rtngExchDetail>",
          "<dlvClf>02</dlvClf>"]
    x.append(f"<ProductNotification><type>{nt}</type>" + "".join(
        f"<item><code>{c}</code><name>" + cdata("상품상세설명 참조") + "</name></item>" for c in NOTI[nt])
        + "</ProductNotification>")
    x.append("<prcCmpExpYn>Y</prcCmpExpYn><prcDscCmpExpYn>Y</prcDscCmpExpYn>")
    x.append("</Product>")
    return "".join(x)


def img_ok(url):
    try:
        r = requests.head(url, timeout=20, allow_redirects=True)
        return r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image")
    except requests.RequestException:
        return False


def main():
    if MODE not in ("dry-run", "test-one", "apply"):
        sys.exit(f"MODE 값이 잘못됐습니다: {MODE}")
    api = A.Eleven()
    have = set()
    for no, p in api.list_products().items():
        c = (p.get("sellerPrdCd") or "").upper() or E.code_of(p.get("prdNm"))
        if c:
            have.add(c)
    print(f"11번가에 이미 있는 상품코드 {len(have)}개")

    nv = N.Naver()
    nv.token()
    items = N.Naver.list_products(nv)
    ol = []
    for it in items:
        ch = (it.get("channelProducts") or [{}])[0]
        if ch.get("brandName") == "오즈라나":
            ol.append((it.get("originProductNo"), ch))
    print(f"시드니셀러 오즈라나 {len(ol)}개")

    trade = {}
    try:
        for p in ozlana_api.get_all_stocks() or []:
            mark = str(p.get("prodMark", "")).strip().upper()
            if mark and mark not in trade and p.get("prodTradePrice") is not None:
                trade[mark] = float(p.get("prodTradePrice"))
    except Exception as e:
        print("오즈라나 도매가 조회 실패", e)
    sup = S.build_supplier({S.BRAND_OL})

    rows, todo, notes = [], [], []
    for origin_no, ch in ol:
        code = (ch.get("sellerManagementCode") or "").upper() or E.code_of(ch.get("name"))
        sp = int(ch.get("discountedPrice") or ch.get("salePrice") or 0)
        p11 = price11(sp)
        fee = int(ch.get("deliveryFee") or 0)
        ctg = CTG.get(str(ch.get("categoryId")))
        tr = trade.get(code)
        cost = round(tr * 1.1 * FX) if tr is not None else None
        margin = round(p11 * (1 - FEE_11ST) - cost) if cost is not None else None
        st = "이미 11번가에 있음" if code in have else ("카테고리 없음" if not ctg else "등록 대상")
        rows.append({"상품코드": code, "시드니셀러상태": ch.get("statusType"), "시드니셀러가": sp, "11번가가": p11,
                     "배송비": fee, "도매가AUD": tr, "원가(GST포함,1000원환율)": cost,
                     "11번가수수료13%후": round(p11 * (1 - FEE_11ST)), "마진": margin,
                     "마진율%": round(margin / p11 * 100, 1) if margin is not None else None,
                     "11번가카테고리": ctg, "처리": st, "상품명": ch.get("name")})
        if ch.get("salePrice") != ch.get("discountedPrice"):
            notes.append(f"{code}: 시드니셀러 할인 있음 (판매가 {ch.get('salePrice')} / 할인가 {ch.get('discountedPrice')}) -> 할인가 기준")
        if st == "등록 대상" and (not ONLY or code in ONLY):
            todo.append((origin_no, code, ctg, p11, fee))

    with open(PRICES, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    out = [f"모드: {MODE}", f"시드니셀러 오즈라나 {len(ol)}개 / 등록 대상 {len(todo)}개",
           f"이미 11번가에 있음: {sum(1 for r in rows if r['처리'] == '이미 11번가에 있음')}개",
           f"카테고리 없음: {[r['상품코드'] for r in rows if r['처리'] == '카테고리 없음']}"]
    ms = [r["마진율%"] for r in rows if r["마진율%"] is not None]
    if ms:
        out.append(f"마진율(11번가 수수료 13%, 원가=도매가+GST, 1AUD=1000원): 최저 {min(ms)}% / 중간 {sorted(ms)[len(ms)//2]}% / 최고 {max(ms)}%")
    out += notes

    if MODE == "dry-run":
        if todo:
            origin_no, code, ctg, p11, fee = todo[0]
            d, err = nv.get(origin_no)
            xml = build_xml(d, code, ctg, p11, fee, 1)
            xml = re.sub(r"<htmlDetail>.*?</htmlDetail>", "<htmlDetail>…</htmlDetail>", xml, flags=re.S)
            out.append(f"\n예시 XML ({code}):\n{xml}")
    else:
        if MODE == "test-one":
            todo = todo[:1]
        done = fail = 0
        for origin_no, code, ctg, p11, fee in todo:
            d, err = nv.get(origin_no)
            time.sleep(0.3)
            if d is None:
                out.append(f"❌ {code} 시드니셀러 상세 조회 실패 {err}")
                fail += 1
                continue
            names, combos = options_of(d)
            bad = [c for c in combos for k in ("optionName1", "optionName2") if c.get(k) and BAD_OPT.search(c[k])]
            if bad:
                out.append(f"❌ {code} 옵션값에 쓸 수 없는 특수문자: {bad[:3]}")
                fail += 1
                continue
            main_img = f"{IMG}/OZLANA/{code}/{code}_main_1.jpg"
            if not img_ok(main_img):
                out.append(f"❌ {code} 대표이미지 없음: {main_img}")
                fail += 1
                continue
            xml = build_xml(d, code, ctg, p11, fee, sum(int(c.get("stockQuantity") or 0) for c in combos) or 1)
            r = api.req("POST", "/prodservices/product", xml)
            try:
                root = A.parse(r)
                rc = (root.findtext(".//resultCode") or "").strip()
                msg = (root.findtext(".//message") or "").strip()
                prd = (root.findtext(".//productNo") or "").strip()
            except Exception:
                rc, msg, prd = "", r.text[:300], ""
            if rc not in ("200", "210") or not prd:
                fail += 1
                out.append(f"❌ {code} 등록 실패 HTTP {r.status_code} {rc} {msg[:400]}")
                if fail >= 5:
                    out.append("실패 5건이라 중단")
                    break
                continue
            done += 1
            line = f"✅ {code} 등록 -> 11번가 상품번호 {prd} (판매가 {p11:,}원, 배송비 {fee:,}원)"
            # 등록 직후 재고를 공급처 기준으로 맞춤
            time.sleep(2)
            srows, serr = api.stocks(prd)
            if srows:
                R = __import__("collections").defaultdict(list)
                brand, c2, new = E.plan_opts(d["originProduct"]["name"], A.opt_list(srows), sup, R, code=code)
                if new and len(new) == len(srows):
                    nset = 0
                    for row, q in zip(srows, new):
                        if E.to_int(row["stckQty"]) != q:
                            ok, m = api.set_stock(prd, row, q)
                            nset += ok
                            time.sleep(0.2)
                    line += f" / 재고 {nset}개 옵션 맞춤 (재고 합계 {sum(new)})"
                else:
                    line += " / ⚠️ 재고 맞춤 못 함 (다음 정기 재고 연동 때 맞춰짐)"
            else:
                line += f" / ⚠️ 재고 조회 실패 {serr}"
            out.append(line)
            time.sleep(1)
        out.insert(2, f"등록 성공 {done} / 실패 {fail}")

    txt = "\n".join(str(x) for x in out)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    print(txt)
    print("\n===== 가격표 =====")
    for r in rows:
        print("|".join(str(r[k]) for k in r))


if __name__ == "__main__":
    main()
