"""
오즈라나(Ozlana) 신발 전체 상품의 Variant에 바코드를 채워 넣습니다.
barcode_mapping.json (같은 폴더, 엑셀에서 추출한 {코드: {색상: {사이즈: 바코드}}} 매핑)을 읽어서
Shopify SKU 패턴 "OZL-{코드}-{색상}-{사이즈}"와 매칭되는 Variant에 바코드를 채워 넣습니다.
main.py, barcode_mapping.json과 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python backfill_ozlana_barcodes.py
"""

import json
import re
import time

import requests

from tag_everugg_products import get_products_by_vendor
from main import get_shopify_access_token, SHOPIFY_STORE

TARGET_VENDOR = "Ozlana"
SKU_PATTERN = re.compile(r"^OZL-([A-Z0-9]+)-([A-Z]+)-(\d+)$", re.IGNORECASE)


def load_mapping():
    with open("barcode_mapping.json", "r", encoding="utf-8") as f:
        return json.load(f)


def update_variant_barcode(shopify_headers, store_domain, variant_id, barcode):
    url = f"https://{store_domain}/admin/api/2024-01/variants/{variant_id}.json"
    payload = {"variant": {"id": variant_id, "barcode": barcode}}
    res = requests.put(url, headers=shopify_headers, json=payload)
    return res.status_code == 200, res.text if res.status_code != 200 else "ok"


def main():
    mapping = load_mapping()
    print(f"바코드 매핑 로드 완료: 스타일 {len(mapping)}개\n")

    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")

    products = get_products_by_vendor(shopify_headers, store_domain, TARGET_VENDOR)
    print(f"'{TARGET_VENDOR}' 벤더 상품 {len(products)}개 조회 완료\n")

    updated = 0
    skipped_already = 0
    no_match_sku = 0
    no_mapping = 0
    failed = 0

    for p in products:
        for v in p.get("variants", []):
            sku = (v.get("sku") or "").strip()
            m = SKU_PATTERN.match(sku)
            if not m:
                no_match_sku += 1
                continue

            code, color, size = m.group(1).upper(), m.group(2).upper(), m.group(3)
            barcode = mapping.get(code, {}).get(color, {}).get(size)

            if not barcode:
                no_mapping += 1
                print(f"[매핑 없음] SKU: {sku}")
                continue

            if (v.get("barcode") or "").strip() == barcode:
                skipped_already += 1
                continue

            ok, info = update_variant_barcode(
                shopify_headers, store_domain, v.get("id"), barcode
            )
            if ok:
                updated += 1
                print(f"[바코드 업데이트] {sku} -> {barcode}")
            else:
                failed += 1
                print(f"[실패] {sku} - {info}")

            time.sleep(0.3)

    print(f"\n완료: 업데이트 {updated}개 / 이미 일치 {skipped_already}개 / "
          f"SKU 패턴 불일치(무시) {no_match_sku}개 / 매핑 없음 {no_mapping}개 / 실패 {failed}개")


if __name__ == "__main__":
    main()
