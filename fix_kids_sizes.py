"""
키즈 신발 사이즈 표기 정리 스크립트 (ozlana-shopify-sync 저장소용)

1) AS UGG(에버어그) 키즈 상품: 사이즈 이름만 바꿈 (SKU는 그대로 -> 재고 동기화 영향 없음)
     25 -> AU 4-5 (EU 21-22)
     27 -> AU 6-7 (EU 23-25)
     29 -> AU 8-10 (EU 26-28)
     31 -> AU 11-12 (EU 29-32)
     33 -> AU 13-2 (EU 33-34)
   Suzie(4/5 ...) / Muffin(21/22 ...) 표기도 같은 형식으로 통일
   34, 35/36, 37/38 은 아직 미확정이라 건드리지 않고 리포트만 출력

2) 키즈/베이비 상품 사이즈 순서 정렬 (오즈웨어 등)
     5/6 -> 7/8 -> 9/10 -> 11/12 -> 13/1 -> 2/3
     S -> M -> L -> XL,  S/M -> L/XL,  Up to 12cm -> 13cm -> 14cm -> 16cm

DRY_RUN=true  : 바뀔 내용만 출력 (기본값)
DRY_RUN=false : 실제로 Shopify에 반영
"""

import os
import re
import sys
import json
import time
import requests

STORE = os.environ.get("SHOPIFY_STORE", "ugg-aus.myshopify.com")
CLIENT_ID = os.environ["SHOPIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SHOPIFY_CLIENT_SECRET"]
API_VERSION = "2025-01"
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

# ---------------------------------------------------------------
# 사이즈 매핑 (AS UGG 전용)
# 34 사이즈가 확인되면 여기에 한 줄 추가하면 됨. 예: "34": "AU 2-3 (EU 35)",
# ---------------------------------------------------------------
AS_SIZE_MAP = {
    # 숫자 표기 (에버어그 코드)
    "25": "AU 4-5 (EU 21-22)",
    "27": "AU 6-7 (EU 23-25)",
    "29": "AU 8-10 (EU 26-28)",
    "31": "AU 11-12 (EU 29-32)",
    "33": "AU 13-2 (EU 33-34)",
    # AU 표기 (Suzie Slipper 등)
    "4/5": "AU 4-5 (EU 21-22)",
    "6/7": "AU 6-7 (EU 23-25)",
    "8/10": "AU 8-10 (EU 26-28)",
    "11/12": "AU 11-12 (EU 29-32)",
    "13/2": "AU 13-2 (EU 33-34)",
    # EU 범위 표기 (Muffin Slippers 등)
    "21/22": "AU 4-5 (EU 21-22)",
    "23/25": "AU 6-7 (EU 23-25)",
    "26/28": "AU 8-10 (EU 26-28)",
    "29/32": "AU 11-12 (EU 29-32)",
    "33/34": "AU 13-2 (EU 33-34)",
}

# 정렬 순서
KIDS_ORDER = ["5/6", "7/8", "9/10", "11/12", "13/1", "2/3"]
BABY_ORDER = ["S", "M", "L", "XL"]
BABY_LONG_ORDER = ["SMALL", "MEDIUM", "LARGE", "EXTRA LARGE"]
SM_ORDER = ["S/M", "L/XL"]
AS_NEW_ORDER = [
    "AU 4-5 (EU 21-22)",
    "AU 6-7 (EU 23-25)",
    "AU 8-10 (EU 26-28)",
    "AU 11-12 (EU 29-32)",
    "AU 13-2 (EU 33-34)",
]

KIDS_PATTERN = re.compile(r"kid|toddler|infant|baby|junior|child", re.I)

GRAPHQL_URL = f"https://{STORE}/admin/api/{API_VERSION}/graphql.json"
TOKEN = None


def get_token():
    r = requests.post(
        f"https://{STORE}/admin/oauth/access_token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    if r.status_code != 200:
        print("토큰 발급 실패:", r.status_code, r.text)
        sys.exit(1)
    return r.json()["access_token"]


def gql(query, variables=None):
    for attempt in range(6):
        r = requests.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers={
                "X-Shopify-Access-Token": TOKEN,
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if r.status_code == 429:
            time.sleep(2 + attempt)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        if "errors" in data:
            throttled = any(
                e.get("extensions", {}).get("code") == "THROTTLED"
                for e in data["errors"]
            )
            if throttled:
                time.sleep(2 + attempt)
                continue
            raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False))
        return data["data"]
    raise RuntimeError("재시도 횟수 초과")


PRODUCTS_QUERY = """
query($cursor: String) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      vendor
      productType
      tags
      options {
        id
        name
        position
        optionValues { id name }
      }
    }
  }
}
"""

RENAME_MUTATION = """
mutation($productId: ID!, $option: OptionUpdateInput!, $vals: [OptionValueUpdateInput!]) {
  productOptionUpdate(productId: $productId, option: $option, optionValuesToUpdate: $vals) {
    userErrors { field message code }
  }
}
"""

REORDER_MUTATION = """
mutation($productId: ID!, $options: [OptionReorderInput!]!) {
  productOptionsReorder(productId: $productId, options: $options) {
    userErrors { field message code }
  }
}
"""


def fetch_all_products():
    products = []
    cursor = None
    while True:
        data = gql(PRODUCTS_QUERY, {"cursor": cursor})
        page = data["products"]
        products.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return products


def is_kids(p):
    text = " ".join([p["title"], p.get("productType") or "", " ".join(p.get("tags") or [])])
    return bool(KIDS_PATTERN.search(text))


def find_size_option(p):
    for opt in p["options"]:
        if "size" in opt["name"].lower():
            return opt
    return None


def sort_key_list(names):
    """정렬 기준을 찾으면 정렬된 이름 리스트 반환, 모르는 값이 섞여 있으면 None"""
    s = set(names)
    for order in (KIDS_ORDER, BABY_ORDER, BABY_LONG_ORDER, SM_ORDER):
        if s <= set(order):
            return sorted(names, key=order.index)
    # AS 새 표기 + 아직 안 바꾼 값(34 등)은 뒤로
    if s & set(AS_NEW_ORDER):
        known = [n for n in names if n in AS_NEW_ORDER]
        unknown = [n for n in names if n not in AS_NEW_ORDER]
        return sorted(known, key=AS_NEW_ORDER.index) + unknown
    cm = [re.search(r"(\d+(?:\.\d+)?)\s*cm", n, re.I) for n in names]
    if all(cm):
        return [n for _, n in sorted(zip([float(m.group(1)) for m in cm], names))]
    return None


def main():
    global TOKEN
    TOKEN = get_token()
    print(f"모드: {'DRY RUN (미리보기)' if DRY_RUN else '실제 반영'}")

    products = fetch_all_products()
    kids = [p for p in products if is_kids(p)]
    print(f"전체 상품 {len(products)}개 중 키즈 상품 {len(kids)}개\n")

    renamed_count = 0
    reordered_count = 0
    leftover = []  # 매핑 안 된 AS 사이즈 (34 등)
    errors = []

    for p in kids:
        opt = find_size_option(p)
        if not opt:
            continue

        values = [dict(v) for v in opt["optionValues"]]
        changes = []

        # 1) AS UGG 이름 변경
        if p["vendor"] == "AS UGG":
            for v in values:
                new_name = AS_SIZE_MAP.get(v["name"].strip())
                if new_name and new_name != v["name"]:
                    changes.append({"id": v["id"], "name": new_name, "old": v["name"]})
                elif v["name"] not in AS_NEW_ORDER and re.fullmatch(r"\d+(/\d+)?", v["name"].strip()):
                    leftover.append(f"{p['title']} : {v['name']}")

            # 같은 옵션 안에서 새 이름이 겹치면 건너뜀 (안전장치)
            new_names = [c["name"] for c in changes] + [
                v["name"] for v in values if v["id"] not in {c["id"] for c in changes}
            ]
            if len(new_names) != len(set(new_names)):
                errors.append(f"{p['title']} : 바꾼 이름이 서로 겹쳐서 건너뜀")
                changes = []

        if changes:
            print(f"[이름변경] {p['title']}")
            print("   " + ", ".join(f"{c['old']} -> {c['name']}" for c in changes))
            renamed_count += 1
            if not DRY_RUN:
                res = gql(RENAME_MUTATION, {
                    "productId": p["id"],
                    "option": {"id": opt["id"]},
                    "vals": [{"id": c["id"], "name": c["name"]} for c in changes],
                })
                ue = res["productOptionUpdate"]["userErrors"]
                if ue:
                    errors.append(f"{p['title']} 이름변경 오류: {ue}")
                    continue
            # 이후 정렬 판단을 위해 로컬 값도 갱신
            change_map = {c["id"]: c["name"] for c in changes}
            for v in values:
                if v["id"] in change_map:
                    v["name"] = change_map[v["id"]]

        # 2) 순서 정렬
        names = [v["name"] for v in values]
        sorted_names = sort_key_list(names)
        if sorted_names and sorted_names != names:
            print(f"[순서정렬] {p['title']}")
            print(f"   {', '.join(names)}  =>  {', '.join(sorted_names)}")
            reordered_count += 1
            if not DRY_RUN:
                id_by_name = {v["name"]: v["id"] for v in values}
                options_input = []
                for o in sorted(p["options"], key=lambda x: x["position"]):
                    if o["id"] == opt["id"]:
                        vals = [{"id": id_by_name[n]} for n in sorted_names]
                    else:
                        vals = [{"id": v["id"]} for v in o["optionValues"]]
                    options_input.append({"id": o["id"], "values": vals})
                res = gql(REORDER_MUTATION, {"productId": p["id"], "options": options_input})
                ue = res["productOptionsReorder"]["userErrors"]
                if ue:
                    errors.append(f"{p['title']} 순서정렬 오류: {ue}")

    print("\n================ 결과 ================")
    print(f"이름 변경 상품: {renamed_count}개")
    print(f"순서 정렬 상품: {reordered_count}개")
    if leftover:
        print(f"\n아직 매핑 안 된 AS 사이즈 ({len(leftover)}건) - 그대로 둠:")
        for line in leftover:
            print("   " + line)
    if errors:
        print(f"\n오류 ({len(errors)}건):")
        for line in errors:
            print("   " + line)
    if DRY_RUN:
        print("\n※ 미리보기 모드였습니다. 내용 확인 후 dry_run=false 로 다시 실행하세요.")


if __name__ == "__main__":
    main()
