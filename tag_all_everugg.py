"""
K-AS 엑셀의 여러 카테고리 시트에 해당하는 코드 목록을 한 번에 순서대로 태그 처리합니다.
tag_everugg_products.py의 함수들을 재사용하며, main.py와 같은 저장소(ozlana-shopify-sync)에
tag_everugg_products.py, main.py와 함께 넣고 실행하세요.

사용법:
    python tag_all_everugg.py
"""

import time

from tag_everugg_products import (
    get_products_by_vendor,
    extract_code,
    add_tag,
    TARGET_VENDOR,
)
from main import get_shopify_access_token, SHOPIFY_STORE

# ==================== 카테고리별 코드 목록 ====================
CATEGORIES = {
    "EVER-ACC": [
        "ASZ020", "ASA006", "ASA007", "ASA008", "ASA014", "ASA035", "ASA060",
        "ASA061", "ASA062", "ASA063", "ASA086", "ASA087", "ASZ046", "ASZ045",
        "ASZ017", "ASA051", "ASZ018", "ASA011", "ASZ055", "ASA012", "ASA012M",
        "ASA017", "ASA018", "ASA019", "ASA024", "ASA050", "ASA015", "ASA057",
        "ASA058", "ASA059", "ASA078", "AS8013", "ASA021", "ASA048", "ASA056",
        "ASA022", "ASA023", "AS8003", "AS8004", "AS8005", "AS8006", "AS8009",
        "AS8011", "ASZ037", "ASZ038", "ASA013", "ASA016", "ASA039", "ASA040",
        "ASA069", "ASA070", "ASA071", "ASA080", "ASZ025", "ASZ011", "ASZ012",
        "ASZ019", "ASZ014N", "ASZ023", "ASZ024", "ASZ027", "ASZ028", "ASZ029",
        "ASZ048", "ASZ047", "ASZ031", "ASZ032", "ASZ033", "ASZ034", "ASZ035",
        "ASZ036", "ASZ041", "ASZ042", "ASZ040", "ASZ039", "ASZ049", "ASZ052",
        "ASZ051", "ASZ050", "ASZ056", "ASZ057", "ASZ058", "ASZ061", "ASZ007",
        "ASZ021", "ASZ022",
    ],
    "EVER-BAG": [
        "AS8007", "AS8008", "AS8010", "ASZ026", "ASA025", "ASA027", "ASA028",
        "ASA029", "ASA030", "ASA031", "ASA032", "ASA036", "ASA034", "ASA037",
        "ASA041", "ASA043", "ASA046", "ASA045", "ASA047", "ASZ044", "ASA049",
        "ASA044", "ASA054", "ASA055", "ASA038", "ASA052", "ASA053", "ASA064",
        "ASA065", "ASA066", "ASA067", "ASA068", "ASA072", "ASA073", "ASA074",
        "ASA075", "ASA076", "ASA077", "ASA081",
    ],
}


def run_category(shopify_headers, store_domain, products, tag, codes):
    target_codes = {c.strip().upper() for c in codes}
    not_matched = set(target_codes)
    tagged = already = failed = 0

    print(f"\n===== 태그: {tag} (대상 {len(target_codes)}개) =====")

    for p in products:
        code = extract_code(p)
        if code not in target_codes:
            continue
        not_matched.discard(code)

        ok, info = add_tag(
            shopify_headers, store_domain, p.get("id"), p.get("tags", ""), tag
        )
        if ok and info == "already_tagged":
            already += 1
        elif ok:
            tagged += 1
            print(f"[태그 추가] {p.get('title')} ({code})")
        else:
            failed += 1
            print(f"[실패] {p.get('title')} ({code}) - {info}")

        time.sleep(0.3)

    print(f"완료: 새로 태그 추가 {tagged}개 / 이미 있음 {already}개 / 실패 {failed}개")
    if not_matched:
        print(f"Shopify에서 못 찾은 코드({len(not_matched)}개): {sorted(not_matched)}")

    return tagged, already, failed, not_matched


def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")

    # 상품 목록은 한 번만 조회해서 모든 카테고리에서 재사용
    products = get_products_by_vendor(shopify_headers, store_domain, TARGET_VENDOR)
    print(f"'{TARGET_VENDOR}' 벤더 상품 {len(products)}개 조회 완료")

    summary = {}
    for tag, codes in CATEGORIES.items():
        result = run_category(shopify_headers, store_domain, products, tag, codes)
        summary[tag] = result

    print("\n===== 전체 요약 =====")
    for tag, (tagged, already, failed, not_matched) in summary.items():
        print(
            f"{tag}: 추가 {tagged} / 이미 있음 {already} / 실패 {failed} / "
            f"못 찾음 {len(not_matched)}"
        )


if __name__ == "__main__":
    main()
