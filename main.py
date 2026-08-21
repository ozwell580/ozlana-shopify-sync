def fetch_everugg_stock_list(endpoint_path, token):
    """AuStock 또는 SydStock 등 전체 재고 목록 조회"""
    url = f"{EVERUGG_BASE_URL}{endpoint_path}"
    params = {"token": token}
    headers = {"Accept": "application/json"}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=20)
        print(f"DEBUG [{endpoint_path}] Status: {res.status_code}")
        print(f"DEBUG [{endpoint_path}] Raw Response: {res.text[:300]}") # 응답 데이터 300자 출력

        if res.status_code == 200:
            body = res.json()
            result = []

            # 1. 응답이 바로 리스트인 경우
            if isinstance(body, list):
                result = body
            # 2. 응답이 딕셔너리(JSON)인 경우
            elif isinstance(body, dict):
                res_obj = body.get("result") or body.get("data") or body.get("items")
                if isinstance(res_obj, list):
                    result = res_obj
                elif isinstance(res_obj, dict):
                    # result 내부에 list가 한 번 더 포함되어 있는 경우
                    result = res_obj.get("data") or res_obj.get("items") or res_obj.get("list") or []

            print(f"-> {endpoint_path} 파싱 성공: {len(result)}건")
            return result if isinstance(result, list) else []
        else:
            print(f"❌ {endpoint_path} 조회 실패 (상태코드 {res.status_code})")
    except Exception as e:
        print(f"❌ {endpoint_path} 조회 중 예외 발생: {e}")
    return []
