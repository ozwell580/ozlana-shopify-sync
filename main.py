def build_everugg_sku_candidates(item):
    """EverUgg 재고 항목 하나에서 쇼피파이 SKU로 매칭해볼 후보 목록 생성.
    실제 업로드 CSV 확인 결과 정식 규칙: AS-{ProductCode}-{ColorName}-{Size}
    단, 가방/액세서리처럼 사이즈가 없는 상품은 AS-{ProductCode}-{ColorName} 형태로 등록되어 있고,
    에버어그 API가 사이즈를 "One Size" 같은 값으로 줄 때도 있어서
    사이즈 유무와 관계없이 2단/3단 후보를 모두 생성함(공백은 하이픈으로도 시도).
    """
    barcode = str(item.get("Barcode", "")).strip().upper()
    product_code = str(item.get("ProductCode", "")).strip().upper()
    color_name = str(item.get("ColorName", "")).strip().upper()
    color_code = str(item.get("ColorCode", "")).strip().upper()
    size = str(item.get("Size", "")).strip().upper()

    color_name_dash = color_name.replace(" ", "-")
    color_code_dash = color_code.replace(" ", "-")

    candidates = []

    # 사이즈가 있으면 3단 SKU 후보
    if product_code and color_name and size:
        candidates.append(f"AS-{product_code}-{color_name}-{size}")
        candidates.append(f"AS-{product_code}-{color_name_dash}-{size}")
    if product_code and color_code and size:
        candidates.append(f"AS-{product_code}-{color_code}-{size}")
        candidates.append(f"AS-{product_code}-{color_code_dash}-{size}")

    # 사이즈 유무와 무관하게 2단 SKU 후보도 항상 생성
    # (에버어그가 "One Size"처럼 값을 채워도 Shopify SKU엔 사이즈가 없는 경우 대응)
    if product_code and color_name:
        candidates.append(f"AS-{product_code}-{color_name}")
        candidates.append(f"AS-{product_code}-{color_name_dash}")
    if product_code and color_code:
        candidates.append(f"AS-{product_code}-{color_code}")
        candidates.append(f"AS-{product_code}-{color_code_dash}")

    if barcode:
        candidates.append(barcode)

    return candidates
