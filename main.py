# ================= EverUgg Specific Sync (수정본) =================
def fetch_everugg_stocks():
    """EverUgg API 인증 및 재고 데이터 가져오기"""
    if not EVERUGG_USER_ID or not EVERUGG_PASSWORD:
        print("EverUgg 계정 정보가 없어 EverUgg 동기화를 건너뜁니다.")
        return []

    try:
        # 1) 토큰 발급 - GET /Api/Token/getToken (쿼리 파라미터 방식)
        login_url = f"{EVERUGG_BASE_URL}/Api/Token/getToken"
        params = {"user": EVERUGG_USER_ID, "password": EVERUGG_PASSWORD}

        res = requests.get(login_url, params=params, timeout=10)

        token = ""
        if res.status_code == 200:
            body = res.json()
            token = body.get("token")
            print(f"-> EverUgg 토큰 발급 결과: {body.get('msg')}")
        else:
            print(f"EverUgg 토큰 발급 실패: {res.status_code} - {res.text}")

        if not token:
            print("EverUgg 토큰이 비어있어 재고 조회를 건너뜁니다.")
            return []

        # 2) 재고 조회 - 아직 정확한 엔드포인트 확인 필요 (아래 참고)
        stock_url = f"{EVERUGG_BASE_URL}/Api/Inventory/GetList"
        req_headers = {"Authorization": f"Bearer {token}"}

        res_stock = requests.get(stock_url, headers=req_headers, timeout=15)
        if res_stock.status_code == 200:
            return res_stock.json().get("data", [])
        else:
            print(f"EverUgg 재고 조회 실패: {res_stock.status_code} - {res_stock.text}")
    except Exception as e:
        print(f"EverUgg API 연동 오류: {e}")

    return []
