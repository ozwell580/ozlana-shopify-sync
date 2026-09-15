"""
에버어그 재고 API(AuStock/SydStock/SydrhStock) 3곳의 원본 응답을 각각 확인합니다.
main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.
"""

import json
import requests
from main import get_everugg_token, EVERUGG_BASE_URL

def main():
    token = get_everugg_token()
    if not token:
        print("토큰 발급 실패")
        return

    for endpoint in ["/Api/Stock/AuStock", "/Api/Stock/SydStock", "/Api/Stock/SydrhStock"]:
        url = f"{EVERUGG_BASE_URL}{endpoint}"
        params = {"token": token}

        res = requests.get(url, params=params, timeout=30)
        print(f"\n{'='*50}")
        print(f"엔드포인트: {endpoint}")
        print(f"Status: {res.status_code}")
        print(f"응답 전체 길이(문자수): {len(res.text)}")

        body = res.json()
        if isinstance(body, dict):
            result = body.get("result", [])
            if isinstance(result, list):
                print(f"항목 수: {len(result)}")

        if "ASA068" in res.text:
            print("✅ 'ASA068' 문자열이 원본 응답 안에 존재함")
        else:
            print("❌ 'ASA068' 문자열이 원본 응답 안에 없음")

if __name__ == "__main__":
    main()
