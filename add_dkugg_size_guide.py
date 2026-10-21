"""
DK UGG 상품 설명 끝에 사이즈 가이드 링크 일괄 추가

- 벤더가 DK UGG 인 상품 전체를 찾아서, 설명(descriptionHtml)에 링크가 없으면 끝에 추가함
- 이미 링크가 있는 상품은 건너뜀 (여러 번 돌려도 중복 안 생김)

환경변수:
  SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET  (main.py와 동일)
  SHOPIFY_STORE         기본값 ugg-aus.myshopify.com
  DKUGG_SIZE_GUIDE_URL  기본값 https://ugg-aus.myshopify.com/pages/dkugg-size-guide
  DRY_RUN               1 이면 바꾸지 않고 대상만 출력
"""

import os
import sys
import time

import requests

STORE = os.environ.get("SHOPIFY_STORE", "ugg-aus.myshopify.com").replace("https://", "").strip("/")
CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
GUIDE_URL = (os.environ.get("DKUGG_SIZE_GUIDE_URL")
             or "https://ugg-aus.myshopify.com/pages/dkugg-size-guide").strip()
DRY_RUN = (os.environ.get("DRY_RUN") or "0").strip() in ("1", "true", "yes")
API_VERSION = "2025-07"

LINK_HTML = f'<p><a href="{GUIDE_URL}" target="_blank">Size Guide / 사이즈 가이드</a></p>'


def get_token():
    r = requests.post(f"https://{STORE}/admin/oauth/access_token",
                      data={"grant_type": "client_credentials",
                            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
                      timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def gql(headers, query, variables=None):
    url = f"https://{STORE}/admin/api/{API_VERSION}/graphql.json"
    for attempt in range(6):
        r = requests.post(url, headers=headers,
                          json={"query": query, "variables": variables or {}}, timeout=60)
        if r.status_code == 429 or (r.ok and "THROTTLED" in r.text):
            time.sleep(2 + attempt * 2)
            continue
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        return data["data"]
    raise RuntimeError("Shopify API throttled")


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET 시크릿이 없습니다.")
        return 1
    headers = {"X-Shopify-Access-Token": get_token(), "Content-Type": "application/json"}

    q = """
    query($after: String) {
      products(first: 100, after: $after, query: "vendor:'DK UGG'") {
        nodes { id title vendor descriptionHtml }
        pageInfo { hasNextPage endCursor }
      }
    }"""
    m = """
    mutation($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id }
        userErrors { field message }
      }
    }"""

    products, after = [], None
    while True:
        res = gql(headers, q, {"after": after})["products"]
        products += [p for p in res["nodes"] if p["vendor"] == "DK UGG"]
        if not res["pageInfo"]["hasNextPage"]:
            break
        after = res["pageInfo"]["endCursor"]
    print(f"DK UGG 상품 {len(products)}개 찾음")

    done = skipped = failed = 0
    for p in products:
        html = p["descriptionHtml"] or ""
        if GUIDE_URL in html:
            skipped += 1
            continue
        if DRY_RUN:
            print(f"  [대상] {p['title']}")
            done += 1
            continue
        out = gql(headers, m, {"input": {"id": p["id"], "descriptionHtml": html + LINK_HTML}})
        errs = out["productUpdate"]["userErrors"]
        if errs:
            print(f"  실패 {p['title']}: {errs}")
            failed += 1
        else:
            done += 1
        time.sleep(0.3)

    label = "추가 대상" if DRY_RUN else "링크 추가"
    print(f"{label} {done}개 / 이미 있음 {skipped}개 / 실패 {failed}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
