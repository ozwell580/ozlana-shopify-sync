"""
11번가 오즈라나 등록 준비용 조회 (읽기만 함, 아무것도 바꾸지 않음)
- 시드니셀러 전체 상품의 코드·가격·배송비 (11번가 가격 기준 확인용)
- 시드니셀러 오즈라나 상품 1개 상세 구조
- 11번가 출고지·반품지·발송마감 템플릿 번호, 기존 오즈웨어 상품 1개 정보
"""
import json
import os
import re
import time

import naver_stock_sync as N
import eleven_api_stock_sync as A
import smartstore_stock_sync as S

SAMPLE_11ST = os.environ.get("SAMPLE_11ST", "9745340301")


def mask(s):
    s = str(s or "")
    return s[:6] + "…" if len(s) > 6 else s


def show_xml(title, r, cut=4000):
    print(f"\n===== {title} : HTTP {r.status_code}")
    txt = r.content.decode("euc-kr", errors="replace")
    # 주소·전화번호는 가림 (공개 로그)
    txt = re.sub(r"<(addr|dtlsAddr|bsAddr|gnrlTlphnNo|prtblTlphnNo|mailNO|mailNoSeq|rcvrNm|addrNm)>([^<]*)<",
                 lambda m: f"<{m.group(1)}>{mask(m.group(2))}<", txt)
    txt = re.sub(r"<htmlDetail>.*?</htmlDetail>", lambda m: m.group(0)[:1500] + "…</htmlDetail>", txt, flags=re.S)
    print(txt[:cut])


def main():
    # ---------------- 11번가
    api = A.Eleven()
    show_xml("출고지 목록", api.req("GET", "/areaservice/outboundarea"))
    show_xml("반품/교환지 목록", api.req("GET", "/areaservice/inboundarea"))
    show_xml("발송마감 템플릿", api.req("GET", "/prodservices/sendCloseList"))
    show_xml(f"기존 상품 {SAMPLE_11ST}", api.req("GET", f"/prodmarketservice/prodmarket/{SAMPLE_11ST}"), cut=8000)
    prods = api.list_products()
    print(f"\n===== 11번가 상품 (판매중·품절) {len(prods)}개: 번호|코드|가격")
    r = api.req("POST", "/prodmarketservice/prodmarket",
                '<?xml version="1.0" encoding="euc-kr"?><SearchProduct><selStatCd>103</selStatCd>'
                '<limit>500</limit><start>1</start><end>500</end></SearchProduct>')
    root = A.parse(r)
    for p in root.findall(".//product")[:3]:
        print("  sample:", {c.tag: (c.text or "")[:60] for c in p})

    # ---------------- 시드니셀러
    nv = N.Naver()
    nv.token()
    items = N.Naver.list_products(nv)
    print(f"\n===== 시드니셀러 상품 {len(items)}개")
    if items:
        print("검색결과 1개 구조:", json.dumps(items[0], ensure_ascii=False)[:2500])
    print("\n===== 시드니셀러 코드표: 원상품번호|브랜드|코드|상태|판매가|할인가|배송비|상품명")
    ol = []
    for it in items:
        for ch in it.get("channelProducts") or []:
            name = ch.get("name") or ""
            code = (ch.get("sellerManagementCode") or "").upper() or (S.CODE_RE.search(name.upper()) or [None, ""])[1]
            brand = ch.get("brandName") or ""
            line = "|".join(str(x) for x in (it.get("originProductNo"), brand, code, ch.get("statusType"),
                                            ch.get("salePrice"), ch.get("discountedPrice"),
                                            ch.get("deliveryFee"), name))
            print(line)
            if "오즈라나" in brand + name or "OZLANA" in (brand + name).upper():
                ol.append(it.get("originProductNo"))
            break
    print(f"\n오즈라나 상품 수: {len(ol)}")
    if ol:
        d, err = nv.get(ol[0])
        if d:
            o = d.get("originProduct") or {}
            slim = json.loads(json.dumps(d, ensure_ascii=False))
            if "detailContent" in slim.get("originProduct", {}):
                slim["originProduct"]["detailContent"] = slim["originProduct"]["detailContent"][:1500] + "…"
            oi = ((slim.get("originProduct") or {}).get("detailAttribute") or {}).get("optionInfo") or {}
            if oi.get("optionCombinations"):
                oi["optionCombinations"] = oi["optionCombinations"][:3] + [f"... 총 {len(oi['optionCombinations'])}개"]
            print("\n===== 시드니셀러 오즈라나 상세 1개")
            print(json.dumps(slim, ensure_ascii=False, indent=1)[:12000])
        else:
            print("상세 조회 실패", err)


if __name__ == "__main__":
    main()
