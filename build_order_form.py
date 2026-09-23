"""
UGG AUS 대량주문 양식 자동 생성 스크립트
================================================
기존 ozlana-shopify-sync 저장소에 이 파일을 추가해서 쓰세요.

동작 방식:
1. 업로드해주신 템플릿 파일(UGGAUS_order_form_template.xlsx)을 "틀"로 그대로 불러옴
   - 사이즈 차트, 서식, 시트 구조는 전부 그대로 유지됨
2. 각 시트(AS UGG / Ozlana / OZWEAR)의 A~H열(브랜드~SKU)만
   Shopify Admin API에서 최신 상품/재고/가격으로 덮어씀
3. 날짜가 들어간 새 파일명으로 저장

필요한 환경변수 (GitHub Actions Secrets에 이미 등록된 것과 동일한 이름 사용):
  SHOPIFY_STORE           예: ugg-aus.myshopify.com
  SHOPIFY_CLIENT_ID
  SHOPIFY_CLIENT_SECRET

사용법:
  python build_order_form.py --template UGGAUS_order_form_template.xlsx --out-dir dist
"""

import os
import sys
import argparse
import datetime
import requests
import openpyxl

API_VERSION = "2024-04"

# 시트 이름 -> Shopify vendor(공급업체) 값 매핑
SHEET_VENDOR_MAP = {
    "AS UGG": "AS UGG",
    "Ozlana": "Ozlana",
    "OZWEAR": "OZWEAR UGG",
}

HEADER = ["브랜드", "상품명", "색상", "사이즈", "가격(AUD)", "재고", "SKU"]


def get_access_token(store, client_id, client_secret):
    """Client Credentials Grant로 매번 새 토큰 발급 (main.py와 동일한 방식)"""
    store = store.replace("https://", "").replace("http://", "").strip("/")
    url = f"https://{store}/admin/oauth/access_token"
    resp = requests.post(
        url,
        json={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_all_active_products(store, token):
    """vendor 필터를 서버에 맡기지 않고, 활성 상품을 전부 받아온 뒤 파이썬에서 직접 매칭한다.
    (vendor 값에 보이지 않는 공백/대소문자 차이가 있어도 놓치지 않기 위함)"""
    store = store.replace("https://", "").replace("http://", "").strip("/")
    products = []
    url = f"https://{store}/admin/api/{API_VERSION}/products.json"
    params = {"limit": 250, "status": "active"}
    headers = {"X-Shopify-Access-Token": token}

    while url:
        resp = requests.get(url, params=params, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        products.extend(data.get("products", []))

        link = resp.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        url = next_url
        params = None

    return products


def normalize_vendor(v):
    """비교용으로 공백/대소문자를 정규화 (눈에 안 보이는 trailing space, 대소문자 차이 방지)"""
    return " ".join((v or "").split()).strip().upper()


def group_products_by_vendor(all_products, vendor_map):
    """vendor_map = {시트이름: vendor값} 기준으로, 정규화 비교하며 상품을 시트별로 나눔"""
    target = {normalize_vendor(v): sheet for sheet, v in vendor_map.items()}
    grouped = {sheet: [] for sheet in vendor_map}
    unmatched_vendors = set()

    for p in all_products:
        key = normalize_vendor(p.get("vendor"))
        sheet = target.get(key)
        if sheet:
            grouped[sheet].append(p)
        elif p.get("vendor"):
            unmatched_vendors.add(p.get("vendor"))

    return grouped, unmatched_vendors


def find_option_index(product, keywords):
    """product['options'] 중 이름이 keywords 중 하나를 포함하는 옵션의 위치(1~3)를 찾음"""
    for opt in product.get("options", []):
        name = (opt.get("name") or "").lower()
        if any(k in name for k in keywords):
            return opt.get("position")  # 1, 2, 3
    return None


def variant_rows(product):
    """한 상품의 모든 variant를 (색상, 사이즈, 가격, 재고, SKU) 행으로 변환"""
    color_idx = find_option_index(product, ["color", "colour", "색상"])
    size_idx = find_option_index(product, ["size", "사이즈"])

    rows = []
    for v in product.get("variants", []):
        color = v.get(f"option{color_idx}") if color_idx else None
        size = v.get(f"option{size_idx}") if size_idx else None
        rows.append(
            {
                "상품명": product.get("title", ""),
                "색상": color or "",
                "사이즈": size or "",
                "가격(AUD)": float(v.get("price") or 0),
                "재고": v.get("inventory_quantity") or 0,
                "SKU": v.get("sku") or "",
            }
        )
    return rows


def write_sheet(ws, vendor_label, rows):
    """A~G열만 새 데이터로 덮어씀 (브랜드~SKU, 순수 조회용 카탈로그). H열부터(사이즈 차트 등)는 절대 건드리지 않음."""
    # 기존에 쓰여있던 A~G열 데이터 영역을 먼저 비움 (row 2부터 기존 max_row까지)
    old_max_row = ws.max_row
    for r in range(2, old_max_row + 1):
        for c in range(1, 8):  # A(1) ~ G(7)
            ws.cell(row=r, column=c).value = None

    # 새 데이터 기록
    for i, row in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=vendor_label)
        ws.cell(row=i, column=2, value=row["상품명"])
        ws.cell(row=i, column=3, value=row["색상"])
        ws.cell(row=i, column=4, value=row["사이즈"])
        ws.cell(row=i, column=5, value=row["가격(AUD)"])
        ws.cell(row=i, column=6, value=row["재고"])
        ws.cell(row=i, column=7, value=row["SKU"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, help="틀로 쓸 기존 xlsx 파일 경로")
    parser.add_argument("--out-dir", default=".", help="결과 파일을 저장할 폴더")
    args = parser.parse_args()

    store = os.environ["SHOPIFY_STORE"]
    client_id = os.environ["SHOPIFY_CLIENT_ID"]
    client_secret = os.environ["SHOPIFY_CLIENT_SECRET"]

    token = get_access_token(store, client_id, client_secret)

    print("전체 활성 상품 조회 중 (한 번만 받아서 이후 시트별로 나눠 씁니다)...")
    all_products = fetch_all_active_products(store, token)
    print(f"전체 활성 상품 {len(all_products)}개 수신")

    grouped, unmatched_vendors = group_products_by_vendor(all_products, SHEET_VENDOR_MAP)
    if unmatched_vendors:
        # 혹시 vendor 표기가 살짝 다른 게 있으면 참고할 수 있도록 로그로 남김
        print(f"[참고] 매핑 대상에 없는 vendor 값 예시: {sorted(unmatched_vendors)[:20]}")

    wb = openpyxl.load_workbook(args.template)  # 서식/사이즈차트 유지 위해 일반 로드

    for sheet_name, vendor in SHEET_VENDOR_MAP.items():
        if sheet_name not in wb.sheetnames:
            print(f"[건너뜀] 템플릿에 '{sheet_name}' 시트가 없습니다.")
            continue

        products = grouped.get(sheet_name, [])
        rows = []
        for p in products:
            rows.extend(variant_rows(p))

        print(f"[{sheet_name}] 상품 {len(products)}개, variant {len(rows)}개 반영")
        write_sheet(wb[sheet_name], vendor, rows)

    os.makedirs(args.out_dir, exist_ok=True)
    today = datetime.date.today().isoformat()
    out_path = os.path.join(args.out_dir, f"UGGAUS_order_form_{today}.xlsx")
    wb.save(out_path)
    print(f"완료: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
