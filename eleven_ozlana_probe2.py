"""
11번가 오즈라나 등록 준비 2 (읽기만 함)
1) 기존 11번가 상품 1개 전체 값 (상세설명 제외)
2) 네이버 카테고리 -> 11번가 카테고리 대응표 (두 곳에 다 있는 상품코드 기준)
3) 시드니셀러 오즈라나 상품별 네이버 카테고리·가격·배송비 + 오즈라나 도매가
"""
import collections
import os
import re

import naver_stock_sync as N
import eleven_api_stock_sync as A
import smartstore_stock_sync as S
import ozlana_api

SAMPLES = os.environ.get("SAMPLE_11ST", "9745340301,9745304145").split(",")


def main():
    api = A.Eleven()
    for no in SAMPLES:
        r = api.req("GET", f"/prodmarketservice/prodmarket/{no}")
        root = A.parse(r)
        print(f"\n===== 11번가 상품 {no} 전체 값")
        for c in root:
            if c.tag == "htmlDetail":
                continue
            v = (c.text or "").strip()
            if len(c):
                v = " ".join(f"{g.tag}={(g.text or '').strip()[:80]}" for g in c.iter() if g is not c)
            print(f"  {c.tag} = {v[:300]}")

    prods = api.list_products()
    ctg11 = {}
    for st in ("103", "104"):
        pass
    # 상품목록 API에는 dispCtgrNo가 있음 -> 다시 받아서 코드별로
    r_all = {}
    for st in A.STATUSES:
        start = 1
        while True:
            body = (f'<?xml version="1.0" encoding="euc-kr"?><SearchProduct><selStatCd>{st}</selStatCd>'
                    f"<limit>500</limit><start>{start}</start><end>{start + 499}</end></SearchProduct>")
            root = A.parse(api.req("POST", "/prodmarketservice/prodmarket", body))
            items = root.findall(".//product")
            for p in items:
                code = (p.findtext("sellerPrdCd") or "").strip().upper()
                if code:
                    r_all[code] = (p.findtext("dispCtgrNo"), p.findtext("prdNm"), p.findtext("selPrc"))
            if len(items) < 500:
                break
            start += 500
    print(f"\n11번가 코드 있는 상품 {len(r_all)}개")

    nv = N.Naver()
    nv.token()
    items = N.Naver.list_products(nv)
    pair = collections.defaultdict(collections.Counter)
    names = {}
    ol = []
    for it in items:
        ch = (it.get("channelProducts") or [{}])[0]
        code = (ch.get("sellerManagementCode") or "").upper()
        nc = ch.get("categoryId")
        names[nc] = ch.get("wholeCategoryName")
        if code in r_all:
            pair[nc][r_all[code][0]] += 1
        if ch.get("brandName") == "오즈라나":
            ol.append(ch)
    print("\n===== 네이버 카테고리 -> 11번가 카테고리 (개수)")
    for nc, cnt in sorted(pair.items(), key=lambda x: -sum(x[1].values())):
        print(f"  {nc} {names.get(nc)} -> {dict(cnt)}")

    trade = {}
    try:
        for p in ozlana_api.get_all_stocks() or []:
            mark = str(p.get("prodMark", "")).strip().upper()
            if mark and mark not in trade:
                trade[mark] = (p.get("prodTradePrice"), p.get("prodMinRetailPrice"), p.get("prodMarketPrice"),
                               p.get("prodName") or p.get("name"))
    except Exception as e:
        print("오즈라나 가격 조회 실패", e)
    print(f"\n===== 시드니셀러 오즈라나 {len(ol)}개: 코드|상태|네이버카테고리|판매가|할인가|배송비|도매가|최소소매가|RRP|11번가대응카테고리|상품명")
    for ch in ol:
        code = (ch.get("sellerManagementCode") or "").upper()
        t = trade.get(code) or trade.get("OZ3" + code[2:] if code.startswith("OZ") else code) or (None, None, None, None)
        nc = ch.get("categoryId")
        m = pair.get(nc)
        print("|".join(str(x) for x in (code, ch.get("statusType"), f"{nc}:{names.get(nc)}", ch.get("salePrice"),
                                       ch.get("discountedPrice"), ch.get("deliveryFee"), t[0], t[1], t[2],
                                       m.most_common(1)[0][0] if m else "-", ch.get("name"))))


if __name__ == "__main__":
    main()
