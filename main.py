def fetch_everugg_stock_list(endpoint_path, token):
    """AuStock 또는 SydStock 등 전체 재고 목록 조회"""
    url = f"{EVERUGG_BASE_URL}{endpoint_path}"
    
    # Header와 Query Parameter 양쪽 모두에 토큰 전달
    headers = {
        "Authorization": f"Bearer {token}",
        "token": token
    }
    params = {"token": token}
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=20)
        if res.status_code == 200:
            body = res.json()
            # body가 리스트이거나 dict 형태인 경우 모두 처리
            if isinstance(body, list):
                result = body
            elif isinstance(body, dict):
                result = body.get("result", body.get("data", []))
            else:
                result = []
            
            print(f"-> {endpoint_path} 조회 성공: {len(result) if isinstance(result, list) else 0}건")
            return result if isinstance(result, list) else []
        else:
            print(f"❌ {endpoint_path} 조회 실패 (상태코드 {res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ {endpoint_path} 조회 중 예외: {e}")
    return []
