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
def fetch_everugg_stocks():
    """EverUgg API 인증 및 재고 데이터 가져오기"""
    if not EVERUGG_USER_ID or not EVERUGG_PASSWORD:
        print("EverUgg 계정 정보가 없어 EverUgg 동기화를 건너뜁니다.")
        return []

    try:
        # 로그인 / 인증 토큰 발급 (API 구조에 따라 인증 URL 호출)
        login_url = f"{EVERUGG_BASE_URL}/Api/Auth/Login"  # Swagger 기반 예시 주소
        payload = {"userId": EVERUGG_USER_ID, "password": EVERUGG_PASSWORD}
        
        # 기본 헤더 설정 (필요시 토큰 방식으로 전환)
        headers = {"Content-Type": "application/json"}
        res = requests.post(login_url, json=payload, headers=headers, timeout=10)
        
        token = ""
        if res.status_code == 200:
            token = res.json().get("token") or res.json().get("data")
        
        # 재고 조회
        stock_url = f"{EVERUGG_BASE_URL}/Api/Inventory/GetList"
        req_headers = {"Authorization": f"Bearer {token}"} if token else headers
        
        res_stock = requests.get(stock_url, headers=req_headers, timeout=15)
        if res_stock.status_code == 200:
            return res_stock.json().get("data", [])
        else:
            print(f"EverUgg 재고 조회 실패: {res_stock.status_code}")
    except Exception as e:
        print(f"EverUgg API 연동 오류 (직접 조회로 전환): {e}")

    return []

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
                            f"{raw_prod_mark}-{color_name}-{size_clean}"
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
        # 필요시 EverUgg SKU 규칙에 맞춘 추가 매핑 로직 작동

if __name__ == "__main__":
    sync_data()
