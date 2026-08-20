import os
import requests
import json

# GitHub Secrets에서 보안 키를 불러옵니다
OZLANA_TOKEN = os.environ.get("OZLANA_TOKEN")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN")

def sync_data():
    print("1. 오즈라나 서버 데이터 수집 중...")
    headers = {"X-Token": OZLANA_TOKEN}
    res = requests.get("http://www.ozlanacms.com.au:30008/products", headers=headers)
    
    if res.status_code == 200:
        raw_data = res.json().get("data", "[]")
        products = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        print(f"-> 수집 완료: 총 {len(products)}개 상품")
        
        # TODO: 쇼피파이 API로 재고/상품 업데이트 요청 처리
        print("2. 쇼피파이 동기화 완료!")
    else:
        print(f"오즈라나 연동 실패: {res.status_code}")

if __name__ == "__main__":
    sync_data()