import requests


def fetch_everugg_stock_list(endpoint_path, token):
    """AuStock 또는 SydStock 등 전체 재고 목록 조회"""
    url = f"{EVERUGG_BASE_URL.rstrip('/')}/{endpoint_path.lstrip('/')}"

    params = {"token": token}
    headers = {"Accept": "application/json"}

    try:
        res = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=20
        )

        print(f"\nDEBUG [{endpoint_path}] URL: {res.url}")
        print(f"DEBUG [{endpoint_path}] Status: {res.status_code}")
        print(f"DEBUG [{endpoint_path}] Content-Type: {res.headers.get('Content-Type')}")
        print(f"DEBUG [{endpoint_path}] Raw Response: {res.text[:1000]}")

        res.raise_for_status()

        try:
            body = res.json()
        except ValueError:
            print(f"❌ JSON 응답이 아닙니다: {res.text[:500]}")
            return []

        print(f"DEBUG body type: {type(body).__name__}")

        # 응답 자체가 리스트
        if isinstance(body, list):
            result = body

        # 응답이 딕셔너리
        elif isinstance(body, dict):
            result = None

            # 자주 사용되는 래퍼 키를 순서대로 확인
            for key in ("result", "data", "items", "list"):
                if key in body and body[key] is not None:
                    result = body[key]
                    print(f"DEBUG 선택된 최상위 키: {key}")
                    break

            # 래퍼 키가 없다면 body 자체가 재고 데이터일 수 있음
            if result is None:
                result = body

            # 내부에 리스트가 한 번 더 들어 있는 경우
            if isinstance(result, dict):
                nested_result = None

                for key in ("data", "items", "list", "result"):
                    if key in result and isinstance(result[key], list):
                        nested_result = result[key]
                        print(f"DEBUG 선택된 내부 키: {key}")
                        break

                if nested_result is not None:
                    result = nested_result
                else:
                    # SKU: 수량 형태의 딕셔너리를 리스트로 변환
                    result = [
                        {
                            "sku": sku,
                            "quantity": quantity
                        }
                        for sku, quantity in result.items()
                    ]

        else:
            print(f"❌ 예상하지 못한 응답 형식: {type(body).__name__}")
            return []

        print(f"✅ {endpoint_path} 파싱 성공: {len(result)}건")

        if result:
            print(f"DEBUG 첫 번째 재고 데이터: {result[0]}")

        return result

    except requests.exceptions.Timeout:
        print(f"❌ {endpoint_path} 요청 시간 초과")
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP 오류: {e}")
    except requests.exceptions.RequestException as e:
        print(f"❌ 네트워크 요청 오류: {e}")
    except Exception as e:
        print(f"❌ {endpoint_path} 처리 중 예외: {type(e).__name__}: {e}")

    return []
