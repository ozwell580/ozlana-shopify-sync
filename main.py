import os
import requests
import json

# ================= Configuration =================
OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

# EverUgg Secrets
EVERUGG_BASE_URL = os.environ.get("EVERUGG_BASE_URL", "http://api.everugg.net.au:9990")
EVERUGG_USER_ID = os.environ.get("EVERUGG_USER_ID")
EVERUGG_PASSWORD = os.environ.get("EVERUGG_PASSWORD")

MARGIN_RATE = 1.21
BASE_URL_OZLANA = "http://www.ozlanacms.com.au:30008"

# ================= Helper Functions =================
def check_env_vars():
    """환경변수 디버깅 출력"""
    print("=== [환경변수 검증] ===")
    if not SHOPIFY_STORE:
        print("❌ SHOPIFY_STORE 설정 안됨")
    else:
        clean_store = SHOPIFY_STORE.replace("https://", "").strip("/")
        print(f"👉 SHOPIFY_STORE: {clean_store}")

    if not SHOPIFY_ACCESS_TOKEN:
        print("❌ SHOPIFY_ACCESS_TOKEN 설정 안됨")
    else:
        token_preview = SHOPIFY_ACCESS_TOKEN[:8] + "..." if len(SHOPIFY_ACCESS_TOKEN) > 8 else SHOPIFY_ACCESS_TOKEN
        print(f"👉 SHOPIFY_ACCESS_TOKEN 시작값: {token_preview}")

    if not EVERUGG_USER_ID or not EVERUGG_PASSWORD:
        print("⚠️ EVERUGG 환경변수가 일부 설정되지 않았습니다.")
    else:
        print(f"👉 EVERUGG 계정: {EVERUGG_USER_ID}")
    print("=========================")

def get_shopify_location_id(shopify_headers):
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/") if SHOPIFY_STORE else ""
    url = f"https://{store_domain}/admin/api/2024-01/locations.json"

    try:
        res = requests.get(url, headers=shopify_headers)
        if res.status_code == 200:
            locations = res.json().get("locations", [])
            if locations:
                loc_id = locations[0]["id"]
                print(f"-> Location ID 조회 성공: {loc_id}")
                return loc_id
        else:
            print(f"[Location API 에러 상세]: {res.text}")
    except Exception as e:
        print(f"Location ID 조회 중 예외 발생: {e}")
    return None

def set_shopify_inventory(inventory_item_id, location_id, quantity, shopify_headers):
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    url = f"https://{store_domain}/admin/api/2024-01/inventory_levels/set.json"
    payload = {
        "location_id": location_id,
        "inventory_item_id": inventory_item_id,
        "available": quantity
    }
    try:
        res = requests.post(url, headers=shopify_headers, json=payload)
        return res.status_code == 200
    except Exception as e:
        print(f"재고 입력 실패 (Item ID {inventory_item_id}): {e}")
        return False

def get_existing_shopify_variants(shopify_headers):
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    sku_map = {}
    url = f"https://{store_domain}/admin/api/2024-01/products.json?limit=250"

    while url:
        try:
            res = requests.get(url, headers=shopify_headers)
            if res.status_code != 200:
                print(f"[Product API 에러 응답]: {res.status_code} - {res.text}")
                break

            products = res.json().get("products", [])
            for p in products:
                for v in p.get("variants", []):
                    sku = v.get("sku")
                    if sku:
                        sku_map[str(sku).strip().upper()] = {
                            "variant_id": v.get("id"),
                            "inventory_item_id": v.get("inventory_item_id")
                        }

            link_header = res.headers.get("Link")
            url = None
            if link_header:
                links = link_header.split(",")
                for link in links:
                    if 'rel="next"' in link:
                        url = link.split(";")[0].strip("<> ")
        except Exception as e:
            print(f"쇼피파이 Variant 매핑 중 오류: {e}")
            break

    return sku_map

# ================= EverUgg Specific Sync =================
def get_everugg_token():
    """EverUgg 토큰 발급 - GET /Api/Token/getToken (쿼리 파라미터: user, password)"""
    if not EVERUGG_USER_ID or not EVERUGG_PASSWORD:
        print("EverUgg 계정 정보가 없어 EverUgg 동기화를 건너뜁니다.")
        return None

    login_url = f"{EVERUGG_BASE_URL}/Api/Token/getToken"
    params = {"user": EVERUGG_USER_ID, "password": EVERUGG_PASSWORD}

    try:
        res = requests.get(login_url, params=params, timeout=10)
        if res.status_code == 200:
            body = res.json()
            token = body.get("token")
            print(f"-> EverUgg 토큰 발급 결과: {body.get('msg')}")
            return token
        else:
            print(f"EverUgg 토큰 발급 실패: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"EverUgg 토큰 발급 중 예외: {e}")
    return None

def fetch_everugg_stock_list(endpoint_path, token):
    """AuStock 또는 SydStock 등 전체 재고 목록 조회 (GET, 쿼리파라미터: token)"""
    url = f"{EVERUGG_BASE_URL}{endpoint_path}"
    params = {"token": token}
    try:
        res = requests.get(url, params=params, timeout=20)
        if res.status_code == 200:
            body = res.json()
            result = body.get("result", [])
            print(f"-> {endpoint_path} 조회 성공: {len(result)}건")
            return result
        else:
            print(f"{endpoint_path} 조회 실패: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"{endpoint_path} 조회 중 예외: {e}")
    return []

def fetch_everugg_stocks():
    """EverUgg 재고 데이터 가져오기 (AuStock + SydStock 합산)"""
    token = get_everugg_token()
    if not token:
        return []

    au_stock = fetch_everugg_stock_list("/Api/Stock/AuStock", token)
    syd_stock = fetch_everugg_stock_list("/Api/Stock/SydStock", token)

    # 같은 Barcode가 두 창고에 모두 있을 수 있으므로 Barcode 기준으로 수량 합산
    combined = {}
    for item in au_stock + syd_stock:
        barcode = str(item.get("Barcode", "")).strip()
        if not barcode:
            continue
        qty = int(item.get("AvailStockQty", 0) or 0)
        if barcode not in combined:
            combined[barcode] = dict(item)
            combined[barcode]["AvailStockQty"] = qty
        else:
            combined[barcode]["AvailStockQty"] += qty

    return list(combined.values())

def build_everugg_sku_candidates(item):
    """EverUgg 재고 항목 하나에서 쇼피파이 SKU로 매칭해볼 후보 목록 생성.
    실제 업로드 CSV 확인 결과 정식 규칙은: AS-{ProductCode}-{ColorName}-{Size}
    예) AS-AS2112M-CHOCOLATE-35
    """
    barcode = str(item.get("Barcode", "")).strip().upper()
    product_code = str(item.get("ProductCode", "")).strip().upper()
    color_name = str(item.get("ColorName", "")).strip().upper()
    color_code = str(item.get("ColorCode", "")).strip().upper()
    size = str(item.get("Size", "")).strip().upper()

    candidates = []
    # 1순위: 실제 CSV 규칙
    if product_code and color_name and size:
        candidates.append(f"AS-{product_code}-{color_name}-{size}")
    # 혹시 모를 예외 대비 백업 패턴들
    if product_code and color_code and size:
        candidates.append(f"AS-{product_code}-{color_code}-{size}")
    if barcode:
        candidates.append(barcode)
    return candidates

# ================= Main Sync Execution =================
def sync_data():
    check_env_vars()

    clean_token = SHOPIFY_ACCESS_TOKEN.strip() if SHOPIFY_ACCESS_TOKEN else ""
    shopify_headers = {
        "X-Shopify-Access-Token": clean_token,
        "Content-Type": "application/json"
    }

    print("1. 쇼피파이 Location ID 및 기존 Variant 수집 중...")
    location_id = get_shopify_location_id(shopify_headers)
    if not location_id:
        print("Error: 쇼피파이 Location ID를 불러오지 못했습니다.")
        return

    shopify_variants = get_existing_shopify_variants(shopify_headers)
    print(f"-> 총 {len(shopify_variants)}개 쇼피파이 SKU 매핑 완료")

    # ----- 2. 오즈라나 (Ozlana) 동기화 -----
    if OZLANA_TOKEN:
        print("2-1. 오즈라나 /stocks API 수집 중...")
        try:
            headers = {"X-Token": OZLANA_TOKEN}
            res_stocks = requests.get(f"{BASE_URL_OZLANA}/stocks", headers=headers)
            if res_stocks.status_code == 200:
                raw_data = res_stocks.json().get("data", [])
                products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data

                updated_count = 0
                store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")

                for prod in products:
                    if not isinstance(prod, dict): continue
                    raw_prod_mark = str(prod.get("prodMark", "")).strip().upper()
                    converted_mark = raw_prod_mark.replace("OZ3", "OZ") if raw_prod_mark.startswith("OZ3") else raw_prod_mark
                    color_name = str(prod.get("colorName", "")).strip().upper()

                    try: trade_price = float(prod.get("prodTradePrice") or 0)
                    except: trade_price = 0.0
                    final_price = f"{round(trade_price * MARGIN_RATE, 2):.2f}" if trade_price > 0 else "0.00"

                    for s in prod.get("stocks", []):
                        if not isinstance(s, dict): continue
                        raw_size = str(s.get("sizeRemark", "")).strip()
                        size_clean = raw_size.split("#")[0] if "#" in raw_size else raw_size
                        stock_num = int(s.get("stockNum", 0))

                        possible_skus = [
                            f"OZL-{converted_mark}-{color_name}-{size_clean}",
                            f"OZL-{raw_prod_mark}-{color_name}-{size_clean}",
                            f"OZL-{converted_mark}-{size_clean}",
                            f"OZL-{raw_prod_mark}-{size_clean}",
                            f"{converted_mark}-{color_name}-{size_clean}",
                            f"{raw_prod_mark}-{size_clean}"
                        ]

                        matched_variant = None
                        for target_sku in possible_skus:
                            if target_sku.upper() in shopify_variants:
                                matched_variant = shopify_variants[target_sku.upper()]
                                break

                        if matched_variant:
                            variant_id = matched_variant["variant_id"]
                            inv_item_id = matched_variant["inventory_item_id"]

                            update_url = f"https://{store_domain}/admin/api/2024-01/variants/{variant_id}.json"
                            update_payload = {"variant": {"id": variant_id, "price": final_price, "inventory_management": "shopify"}}
                            requests.put(update_url, headers=shopify_headers, json=update_payload)

                            if inv_item_id and set_shopify_inventory(inv_item_id, location_id, stock_num, shopify_headers):
                                updated_count += 1

                print(f"-> [Ozlana] 총 {updated_count}개 옵션 재고 세팅 완료!")
        except Exception as e:
            print(f"Ozlana 동기화 중 에러: {e}")

    # ----- 3. 에버어그 (EverUgg) 동기화 -----
    print("2-2. EverUgg API 수집 중...")
    everugg_data = fetch_everugg_stocks()
    if everugg_data:
        print(f"-> EverUgg 데이터 {len(everugg_data)}건 수집 완료!")

        eu_updated_count = 0
        eu_unmatched = []

        for item in everugg_data:
            qty = int(item.get("AvailStockQty", 0) or 0)
            candidates = build_everugg_sku_candidates(item)

            matched_variant = None
            for target_sku in candidates:
                if target_sku.upper() in shopify_variants:
                    matched_variant = shopify_variants[target_sku.upper()]
                    break

            if matched_variant:
                inv_item_id = matched_variant["inventory_item_id"]
                if inv_item_id and set_shopify_inventory(inv_item_id, location_id, qty, shopify_headers):
                    eu_updated_count += 1
            else:
                eu_unmatched.append(candidates[0] if candidates else "UNKNOWN")

        print(f"-> [EverUgg] 총 {eu_updated_count}개 옵션 재고 세팅 완료!")
        if eu_unmatched:
            print(f"-> [EverUgg] 매칭 실패 SKU 예시 (최대 10개): {eu_unmatched[:10]}")
    else:
        print("-> EverUgg 재고 데이터를 가져오지 못했습니다.")

if __name__ == "__main__":
    sync_data()
