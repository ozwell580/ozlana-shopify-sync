"""
EverUgg API의 Price 필드가 GST 포함/불포함인지 직접 확인하는 디버그 스크립트.
main.py의 로직을 그대로 가져와서, 특정 ProductCode의 원본 데이터만 출력한다.

사용법:
  python check_everugg_price.py AS2055K
"""
import os
import sys
import requests

EVERUGG_BASE_URL = os.environ.get("EVERUGG_BASE_URL", "http://api.everugg.net.au:9990")
EVERUGG_USER_ID = os.environ.get("EVERUGG_USER_ID")
EVERUGG_PASSWORD = os.environ.get("EVERUGG_PASSWORD")


def get_everugg_token():
    login_url = f"{EVERUGG_BASE_URL}/Api/Token/getToken"
    params = {"user": EVERUGG_USER_ID, "password": EVERUGG_PASSWORD}
    res = requests.get(login_url, params=params, timeout=10)
    res.raise_for_status()
    body = res.json()
    return body.get("result", {}).get("token")


def fetch_stock_list(endpoint_path, token):
    url = f"{EVERUGG_BASE_URL.rstrip('/')}/{endpoint_path.lstrip('/')}"
    res = requests.get(url, params={"token": token}, timeout=20)
    res.raise_for_status()
    body = res.json()
    return body.get("result", [])


def main():
    if len(sys.argv) < 2:
        print("사용법: python check_everugg_price.py <ProductCode>")
        return 1

    target_code = sys.argv[1].strip().upper()
    token = get_everugg_token()
    if not token:
        print("토큰 발급 실패")
        return 1

    found = []
    for endpoint in ["/Api/Stock/AuStock", "/Api/Stock/SydStock", "/Api/Stock/SydrhStock"]:
        items = fetch_stock_list(endpoint, token)
        for item in items:
            if str(item.get("ProductCode", "")).strip().upper() == target_code:
                found.append((endpoint, item))

    if not found:
        print(f"'{target_code}' 코드로 된 항목을 찾지 못했습니다.")
        return 0

    print(f"'{target_code}' 검색 결과 {len(found)}건:\n")
    for endpoint, item in found:
        print(f"[{endpoint}]")
        print(f"  ProductName : {item.get('ProductName')}")
        print(f"  ColorName   : {item.get('ColorName')}")
        print(f"  Size        : {item.get('Size')}")
        print(f"  Price       : {item.get('Price')}   <- 이게 원가(순수/GST포함 여부 확인 대상)")
        print(f"  RetailPrice : {item.get('RetailPrice')}")
        print(f"  Price * 1.1 = {round(float(item.get('Price', 0) or 0) * 1.1, 2)}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
