"""
Shopify 스토어에 등록된 모든 Location을 확인합니다.
"""

import requests
from main import get_shopify_access_token, SHOPIFY_STORE

def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")
    url = f"https://{store_domain}/admin/api/2024-01/locations.json"

    res = requests.get(url, headers=shopify_headers)
    print(f"Status: {res.status_code}")
    locations = res.json().get("locations", [])
    print(f"총 Location 개수: {len(locations)}\n")
    for loc in locations:
        print(loc)

    # 실제 이 variant의 inventory_item_id로 각 location별 재고도 확인
    inventory_item_id = 50972211839161
    inv_url = f"https://{store_domain}/admin/api/2024-01/inventory_levels.json?inventory_item_ids={inventory_item_id}"
    inv_res = requests.get(inv_url, headers=shopify_headers)
    print(f"\n특정 variant(ASA068 Saddle Brown)의 재고 현황:")
    print(inv_res.json())

if __name__ == "__main__":
    main()
