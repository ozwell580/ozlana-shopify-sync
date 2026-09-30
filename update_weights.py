"""
AUSTRALIAN STEPS - 상품 청구 무게 일괄 설정 스크립트

배송비 안내 이미지 기준으로 모든 상품 옵션(variant)에 무게를 넣습니다.
  1kg : 키즈 신발, 액세서리(스카프/모자/장갑/귀마개/가방 등)
  2kg : 키즈 롱부츠, 성인 슬리퍼, 숏부츠
  3kg : 성인 미니부츠, 미들~롱 부츠
  2kg : 조끼(베스트)
  3kg : 코트, 재킷 등 그 외 의류
  에버어그(AS UGG) 모델명만 있는 신발은 스타일 코드 번호대로 분류
    AS2, AS5, AS7 → 2kg / AS3, AS6 → 3kg / AS4 → 4kg

사용법 (GitHub Actions 환경변수)
  SHOPIFY_STORE         : xxx.myshopify.com
  SHOPIFY_CLIENT_ID     : Dev Dashboard 앱 Client ID
  SHOPIFY_CLIENT_SECRET : Dev Dashboard 앱 Client Secret
  SHOPIFY_API_VERSION   : (선택) 기본 2026-07
  DRY_RUN               : true = 미리보기만 (기본값), false = 실제 적용

실행 결과는 weight_plan.csv 로 저장됩니다. 먼저 DRY_RUN=true 로 돌려서
분류가 맞는지 확인한 뒤 DRY_RUN=false 로 실제 적용하세요.
"""

import csv
import json
import os
import re
import sys
import time
from collections import Counter

import requests

# ─────────────────────────────────────────────
# 무게 기준 (kg) - 필요하면 여기 숫자만 바꾸세요
# ─────────────────────────────────────────────
KIDS_KG = 1.0        # 키즈 신발
KIDS_TALL_KG = 2.0   # 키즈 롱/톨 부츠
ACC_KG = 1.0         # 액세서리, 가방
SHORT_KG = 2.0       # 성인 슬리퍼, 숏부츠
MINI_KG = 3.0        # 성인 미니부츠
TALL_KG = 3.0        # 성인 미들~롱 부츠
VEST_KG = 2.0        # 조끼(베스트)
APPAREL_KG = 3.0     # 코트, 재킷 등 그 외 의류
# 에버어그 스타일 코드 번호대별 무게 (키워드로 분류 안 된 상품에만 적용)
EVER_SERIES_KG = {
    "AS2": 2.0,  # 슬리퍼, 로퍼
    "AS3": 3.0,  # 부츠
    "AS4": 4.0,
    "AS5": 2.0,  # 뮬, 신발
    "AS6": 3.0,  # 굽 있는 부츠
    "AS7": 2.0,  # 로퍼, 신발
}
DEFAULT_KG = 2.0     # 어디에도 해당 안 되는 상품 (리포트에서 꼭 확인)

# ─────────────────────────────────────────────
# 분류 키워드 (상품명 + 상품유형 + 태그에서 찾음)
# ─────────────────────────────────────────────
APPAREL_PAT = r"\b(apparel|jacket|jackets|coat|coats|vest|vests|gilet|hoodie|cardigan|sweater|jumper|pullover|pants|poncho|cape)\b"
ACC_PAT = (
    r"\b(acc|accessory|accessories|scarf|scarves|hat|hats|beanie|bucket|cap|glove|gloves|"
    r"mitten|mittens|earmuff|earmuffs|headband|bag|bags|tote|pouch|clutch|backpack|"
    r"keyring|keyrings|charms|wallet|sock|socks|snood|snoods|cushion|cushions|case|cases)\b"
)
KIDS_PAT = r"\b(kid|kids|toddler|baby|infant|junior|youth|children)\b"
TALL_PAT = r"\b(tall|long|mid|middle|knee)\b"

STORE = os.environ.get("SHOPIFY_STORE", "").strip().replace("https://", "").rstrip("/")
CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-07").strip()
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"
REPORT_FILE = "weight_plan.csv"

UNIT_TO_KG = {
    "KILOGRAMS": 1.0,
    "GRAMS": 0.001,
    "POUNDS": 0.45359237,
    "OUNCES": 0.028349523125,
}


def has(pattern, text):
    return re.search(pattern, text, re.IGNORECASE) is not None


def classify(title, product_type, tags):
    """상품 하나의 청구 무게와 적용된 규칙 이름을 돌려줌"""
    text = " ".join([title or "", product_type or "", " ".join(tags or [])])

    if has(r"\b(vest|vests|gilet)\b", text):
        return VEST_KG, "조끼"
    if has(APPAREL_PAT, text):
        return APPAREL_KG, "코트/재킷 등 의류"
    if has(ACC_PAT, text):
        return ACC_KG, "액세서리/가방"
    if has(KIDS_PAT, text):
        if has(TALL_PAT, title or ""):
            return KIDS_TALL_KG, "키즈 롱부츠"
        return KIDS_KG, "키즈"
    if has(r"\bmini\b", title or ""):
        return MINI_KG, "미니부츠"
    if has(TALL_PAT, title or ""):
        return TALL_KG, "미들~롱 부츠"
    if has(r"\b(slipper|slippers|scuff|scuffs|slide|slides|mule|mules|moccasin|moccasins|maryjane|mary jane|slip-on|slip on|footbed|sandal|sandals|short|boot|boots|shoe|shoes|sneaker|sneakers|loafer|loafers|clog|clogs|flat|flats)\b", text):
        return SHORT_KG, "슬리퍼/숏부츠"
    m = re.search(r"\((AS\d)\d{2,}\w*\)\s*$", title or "", re.IGNORECASE)
    if m:
        series = m.group(1).upper()
        if series in EVER_SERIES_KG:
            return EVER_SERIES_KG[series], f"에버어그 {series} 번호대"
    return DEFAULT_KG, "미분류(기본값)"


def get_token():
    url = f"https://{STORE}/admin/oauth/access_token"
    r = requests.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    if r.status_code != 200:
        print(f"[오류] 토큰 발급 실패: {r.status_code} {r.text}")
        sys.exit(1)
    token = r.json().get("access_token")
    if not token:
        print(f"[오류] 응답에 access_token 이 없습니다: {r.text}")
        sys.exit(1)
    return token


def gql(token, query, variables=None):
    url = f"https://{STORE}/admin/api/{API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    for attempt in range(8):
        r = requests.post(url, json={"query": query, "variables": variables or {}}, headers=headers, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
        data = r.json()
        errors = data.get("errors")
        if errors:
            throttled = any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors)
            if throttled:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(json.dumps(errors, ensure_ascii=False))
        return data["data"]
    raise RuntimeError("GraphQL 요청이 계속 실패했습니다 (속도 제한).")


PRODUCTS_QUERY = """
query($cursor: String) {
  products(first: 8, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      productType
      tags
      variants(first: 100) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          inventoryItem { measurement { weight { unit value } } }
        }
      }
    }
  }
}
"""

MORE_VARIANTS_QUERY = """
query($id: ID!, $cursor: String) {
  product(id: $id) {
    variants(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        inventoryItem { measurement { weight { unit value } } }
      }
    }
  }
}
"""

UPDATE_MUTATION = """
mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    userErrors { field message }
  }
}
"""


def variant_kg(variant):
    weight = ((variant.get("inventoryItem") or {}).get("measurement") or {}).get("weight") or {}
    value = weight.get("value")
    unit = weight.get("unit")
    if value is None or unit not in UNIT_TO_KG:
        return 0.0
    return round(float(value) * UNIT_TO_KG[unit], 3)


def fetch_all_products(token):
    products = []
    cursor = None
    while True:
        data = gql(token, PRODUCTS_QUERY, {"cursor": cursor})
        block = data["products"]
        for p in block["nodes"]:
            variants = list(p["variants"]["nodes"])
            v_page = p["variants"]["pageInfo"]
            while v_page["hasNextPage"]:
                more = gql(token, MORE_VARIANTS_QUERY, {"id": p["id"], "cursor": v_page["endCursor"]})
                vb = more["product"]["variants"]
                variants.extend(vb["nodes"])
                v_page = vb["pageInfo"]
            p["all_variants"] = variants
            products.append(p)
        print(f"  상품 {len(products)}개 불러옴...")
        if not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]
    return products


def update_product(token, product_id, variant_ids, kg):
    errors = []
    for i in range(0, len(variant_ids), 100):
        chunk = variant_ids[i:i + 100]
        payload = [
            {
                "id": vid,
                "inventoryItem": {"measurement": {"weight": {"value": kg, "unit": "KILOGRAMS"}}},
            }
            for vid in chunk
        ]
        data = gql(token, UPDATE_MUTATION, {"productId": product_id, "variants": payload})
        user_errors = data["productVariantsBulkUpdate"]["userErrors"]
        if user_errors:
            errors.extend(user_errors)
        time.sleep(0.3)
    return errors


def main():
    if not STORE or not CLIENT_ID or not CLIENT_SECRET:
        print("[오류] SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET 환경변수를 확인하세요.")
        sys.exit(1)

    print(f"스토어: {STORE} / API: {API_VERSION}")
    print("모드: " + ("미리보기 (DRY_RUN) - 실제 변경 없음" if DRY_RUN else "실제 적용"))

    token = get_token()
    print("상품 불러오는 중...")
    products = fetch_all_products(token)

    rule_counter = Counter()
    rows = []
    total_updated = 0
    total_failed = 0

    for p in products:
        kg, rule = classify(p["title"], p.get("productType"), p.get("tags"))
        rule_counter[rule] += 1
        variants = p["all_variants"]
        to_update = [v["id"] for v in variants if abs(variant_kg(v) - kg) > 0.001]
        current = sorted({variant_kg(v) for v in variants})

        status = "변경 없음"
        if to_update:
            if DRY_RUN:
                status = "변경 예정"
            else:
                errs = update_product(token, p["id"], to_update, kg)
                if errs:
                    status = "실패: " + "; ".join(e["message"] for e in errs)
                    total_failed += 1
                else:
                    status = "적용 완료"
                    total_updated += len(to_update)

        rows.append({
            "상품명": p["title"],
            "상품유형": p.get("productType") or "",
            "적용 규칙": rule,
            "설정 무게(kg)": kg,
            "옵션 수": len(variants),
            "변경할 옵션 수": len(to_update),
            "현재 무게(kg)": ", ".join(str(c) for c in current),
            "결과": status,
        })

    rows.sort(key=lambda r: (r["적용 규칙"] != "미분류(기본값)", r["적용 규칙"], r["상품명"]))

    with open(REPORT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["상품명"])
        writer.writeheader()
        writer.writerows(rows)

    print("\n===== 분류 결과 =====")
    for rule, count in rule_counter.most_common():
        print(f"  {rule}: {count}개 상품")

    unmatched = [r["상품명"] for r in rows if r["적용 규칙"] == "미분류(기본값)"]
    if unmatched:
        print(f"\n[확인 필요] 미분류 상품 {len(unmatched)}개 (기본값 {DEFAULT_KG}kg 적용):")
        for name in unmatched[:50]:
            print(f"  - {name}")
        if len(unmatched) > 50:
            print(f"  ... 외 {len(unmatched) - 50}개 (weight_plan.csv 참고)")

    if DRY_RUN:
        pending = sum(r["변경할 옵션 수"] for r in rows)
        print(f"\n미리보기 완료: 변경 예정 옵션 {pending}개. weight_plan.csv 를 확인하세요.")
    else:
        print(f"\n적용 완료: 옵션 {total_updated}개 무게 변경, 실패 상품 {total_failed}개.")


if __name__ == "__main__":
    main()
