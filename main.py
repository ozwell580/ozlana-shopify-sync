def fetch_everugg_stock_list(endpoint_path, token):
    """AuStock 또는 SydStock 등 전체 재고 목록 조회"""
    url = f"{EVERUGG_BASE_URL}{endpoint_path}"
    
    # EverUgg API 명세 기준 쿼리 파라미터 전달
    params = {"token": token}
    headers = {"Content-Type": "application/json"}
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=20)
        print(f"DEBUG [{endpoint_path}] - Status Code: {res.status_code}")
        print(f"DEBUG [{endpoint_path}] - Response Text: {res.text[:300]}") # 응답 앞부분 출력
        
        if res.status_code == 200:
            body = res.json()
            if isinstance(body, list):
                result = body
            elif isinstance(body, dict):
                result = body.get("result", body.get("data", []))
            else:
                result = []
            
            print(f"-> {endpoint_path} 조회 성공: {len(result) if isinstance(result, list) else 0}건")
            return result if isinstance(result, list) else []
        else:
            print(f"❌ {endpoint_path} 조회 실패: {res.status_code}")
    except Exception as e:
        print(f"❌ {endpoint_path} 예외 발생: {e}")
    return []
