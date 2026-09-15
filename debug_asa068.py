"""
에버어그 API 재고 데이터 중 특정 ProductCode의 원본 데이터를 그대로 출력합니다.
main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.
"""

from main import fetch_everugg_stocks, build_everugg_sku_candidates

TARGET_CODES = ["ASA068", "ASA076", "ASA075"]

def main():
    data = fetch_everugg_stocks()
    print(f"EverUgg 데이터 {len(data)}건 수집 완료\n")

    for target in TARGET_CODES:
        print(f"=== {target} ===")
        found = [item for item in data if str(item.get("ProductCode", "")).strip().upper() == target]
        if not found:
            print(f"  -> API 데이터에 {target}가 아예 없음!\n")
            continue
        for item in found:
            print(f"  ColorName={item.get('ColorName')!r} ColorCode={item.get('ColorCode')!r} "
                  f"Size={item.get('Size')!r} Barcode={item.get('Barcode')!r} "
                  f"AvaiStockQty={item.get('AvaiStockQty')!r}")
            candidates = build_everugg_sku_candidates(item)
            print(f"  -> 생성된 SKU 후보: {candidates}")
        print()

if __name__ == "__main__":
    main()
