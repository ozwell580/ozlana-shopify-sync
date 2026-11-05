"""
네이버 커머스API 연결 테스트 (시드니셀러)
------------------------------------------
1) 지금 실행 중인 컴퓨터의 바깥 IP를 보여줌 (커머스API센터 'API호출 IP'에 등록할 값)
2) 토큰 발급 시도
3) 상품 몇 개 조회 시도

필요한 GitHub 시크릿
  SYDNEY_CLIENT_ID      : 애플리케이션 ID
  SYDNEY_CLIENT_SECRET  : 애플리케이션 시크릿
선택
  NAVER_PROXY           : 고정 IP 프록시 주소 (예: http://user:pass@1.2.3.4:3128). 비우면 직접 호출
"""

import base64
import json
import os
import sys
import time

import bcrypt
import requests

API = "https://api.commerce.naver.com/external"
CLIENT_ID = os.environ.get("SYDNEY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SYDNEY_CLIENT_SECRET", "").strip()
PROXY = os.environ.get("NAVER_PROXY", "").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None


def show_ip():
    try:
        ip = requests.get("https://api.ipify.org", proxies=PROXIES, timeout=15).text.strip()
        print(f"[1] 호출 IP: {ip}  ({'프록시 경유' if PROXY else '직접 호출'})")
    except Exception as e:
        print(f"[1] IP 확인 실패: {e}")


def get_token():
    ts = str(int(time.time() * 1000))
    hashed = bcrypt.hashpw(f"{CLIENT_ID}_{ts}".encode("utf-8"), CLIENT_SECRET.encode("utf-8"))
    sign = base64.b64encode(hashed).decode("utf-8")
    r = requests.post(
        f"{API}/v1/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "timestamp": ts,
            "client_secret_sign": sign,
            "grant_type": "client_credentials",
            "type": "SELF",
        },
        proxies=PROXIES,
        timeout=30,
    )
    print(f"[2] 토큰 발급 응답: HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:1000])
        return None
    print("    토큰 발급 성공")
    return r.json().get("access_token")


def list_products(token):
    r = requests.post(
        f"{API}/v1/products/search",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps({"page": 1, "size": 5}),
        proxies=PROXIES,
        timeout=30,
    )
    print(f"[3] 상품 조회 응답: HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:1000])
        return False
    data = r.json()
    print(f"    전체 상품 수: {data.get('totalElements')}")
    for item in data.get("contents", []):
        for ch in item.get("channelProducts", []):
            print(f"    - 원상품 {item.get('originProductNo')} / 상품번호 {ch.get('channelProductNo')} / "
                  f"{ch.get('name')} / 재고 {ch.get('stockQuantity')}")
    return True


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("SYDNEY_CLIENT_ID / SYDNEY_CLIENT_SECRET 시크릿이 비어 있어요.")
        sys.exit(1)
    show_ip()
    token = get_token()
    if not token:
        print("\n결과: 토큰 발급 실패. 'IP_NOT_ALLOWED'가 보이면 위 [1]의 IP가 등록되지 않은 것이고,"
              "\n      'client_secret_sign' 관련 오류면 ID/시크릿 값을 다시 확인하세요.")
        sys.exit(1)
    ok = list_products(token)
    print("\n결과:", "연결 성공" if ok else "토큰은 받았지만 상품 조회 실패 (위 메시지 확인)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
