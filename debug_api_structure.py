"""
에버어그 SydStock API의 원본 응답을 자세히 확인합니다.
- 응답 최상위 키가 무엇인지
- 페이지네이션 관련 필드(total, page, pageSize 등)가 있는지
- 실제 항목 수와 ASA068 포함 여부

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

    url = f"{EVERUGG_BASE_URL}/Api/Stock/SydStock"
    params = {"token": token}

    res = requests.get(url, params=params, timeout=30)
    print(f"Status: {res.status_code}")
    print(f"응답 전체 길이(문자수): {len(res.text)}")

    body = res.json()
    print(f"\n최상위 타입: {type(body).__name__}")

    if isinstance(body, dict):
        print(f"최상위 키 목록: {list(body.keys())}")
        for key in body.keys():
            val = body[key]
            if isinstance(val, list):
                print(f"  '{key}' -> 리스트, 길이 {len(val)}")
            else:
                print(f"  '{key}' -> {val!r}")

        # result 안에 페이지네이션 정보가 있는지도 확인
        result = body.get("result")
        if isinstance(result, dict):
            print(f"\n'result' 내부 키 목록: {list(result.keys())}")

    # ASA068이 원본 텍스트에 포함되어 있는지 직접 검색
    if "ASA068" in res.text:
        print("\n✅ 'ASA068' 문자열이 원본 응답 안에 존재함")
    else:
        print("\n❌ 'ASA068' 문자열이 원본 응답 안에 없음")

if __name__ == "__main__":
    main()
