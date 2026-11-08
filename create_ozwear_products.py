"""
오즈웨어 API에 있는데 Shopify('OZWEAR UGG')에 없는 상품을 Shopify에 새로 등록합니다.
기존 오즈웨어 상품과 같은 형식으로 만듭니다.
  - 제목: 'UGG 상품명 (코드)'   - 태그: 코드   - 상품유형: Footwear(의류·잡화는 이름으로 판단)
  - 옵션: Color / Size          - SKU = 바코드 = 오즈웨어 SKU
  - 가격: 오즈웨어 API 가격 x PRICE_MULTIPLIER (기존 상품 +10% 기준, 기본 1.1)
  - 무게: update_weights.py 규칙 그대로
  - 재고: 등록 직후 오즈웨어 재고로 바로 입력
  - 이미지: API imageUrl 이 있으면 연결 (없으면 나중에 add_ozwear_images.py 로)

환경변수
  MODE   = dry-run(기본, 미리보기만) / apply(실제 등록)
  CODES  = 쉼표로 구분한 스타일 코드
  REF_CODE = 가격 기준을 확인할 기존 상품 코드 (기본 OB1145)
  OZWEAR_API_KEY, OZWEAR_API_SECRET, SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET
결과는 create_ozwear_report.txt 로 저장됩니다.
"""

import json
import os
import re
import sys
import time

import requests

from sync_ozwear_inventory import (
    OZWEAR_BASE_URL,
    get_shopify_access_token,
    get_shopify_location_id,
    get_ozwear_token,
)
from update_weights import classify

MODE = (os.environ.get("MODE") or "dry-run").strip().lower()
CODES = [c.strip().upper() for c in (os.environ.get("CODES") or "").split(",") if c.strip()]
REF_CODE = (os.environ.get("REF_CODE") or "OB1145").strip().upper()
PRICE_MULTIPLIER = float(os.environ.get("PRICE_MULTIPLIER") or "1.1")
VENDOR = "OZWEAR UGG"
API_VERSION = "2024-01"
SIZE_GUIDE = '<p><a href="https://ugg-aus.myshopify.com/pages/ozwear-size-guide-chart">사이즈 가이드 보기</a></p>'

PRICE_KEYS = ("price", "wholesalePrice", "tradePrice", "salePrice", "unitPrice", "costPrice", "sellPrice")
DESC_KEYS = ("description", "material", "materials", "detail", "details", "remark", "desc")

LINES = []


def log(msg=""):
    print(msg)
    LINES.append(str(msg))


def save_report():
    with open("create_ozwear_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")


# ------------------------------------------------------------ 오즈웨어 API
def api_products_by_code(tok, code):
    """해당 코드의 상품 옵션 전체 (코드가 정확히 같은 것만)"""
    headers = {"api_key": tok, "Content-Type": "application/json", "Accept": "application/json"}
    out, page = [], 1
    while True:
        r = requests.post(f"{OZWEAR_BASE_URL}/products", headers=headers,
                          json={"code": code, "page": page, "pageSize": 100}, timeout=60)
        r.raise_for_status()
        data = r.json().get("data") or {}
        items = data.get("list") or []
        out.extend(items)
        total = int(data.get("total") or 0)
        if not items or len(items) < 100 or (total and page * 100 >= total):
            break
        page += 1
        time.sleep(0.3)
    return [p for p in out if str(p.get("code", "")).strip().upper() == code]


def api_stock(tok, skus):
    headers = {"api_key": tok, "Content-Type": "application/json"}
    stock = {}
    for i in range(0, len(skus), 50):
        r = requests.post(f"{OZWEAR_BASE_URL}/products/stock", headers=headers,
                          json={"skus": skus[i:i + 50], "productIds": []}, timeout=60)
        r.raise_for_status()
        for it in (r.json().get("data") or {}).get("list") or []:
            k = str(it.get("sku", "")).strip()
            if k:
                try:
                    stock[k] = max(0, int(float(it.get("stock") or 0)))
                except (TypeError, ValueError):
                    stock[k] = 0
        time.sleep(0.3)
    return stock


def pick(item, keys):
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return k, item[k]
    return None, None


def to_float(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ Shopify
def shopify_codes(headers, domain):
    """이미 등록된 오즈웨어 상품 코드 (태그 + 제목 괄호 속 코드)"""
    codes = set()
    url = f"https://{domain}/admin/api/{API_VERSION}/products.json?limit=250&vendor={requests.utils.quote(VENDOR)}&fields=id,title,tags"
    while url:
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        for p in r.json().get("products", []):
            for t in str(p.get("tags") or "").split(","):
                if t.strip():
                    codes.add(t.strip().upper())
            for m in re.findall(r"\(([A-Z0-9 ]+)\)\s*$", str(p.get("title", "")).upper()):
                codes.add(m.replace(" ", ""))
        url = None
        for link in (r.headers.get("Link") or "").split(","):
            if 'rel="next"' in link:
                url = link.split(";")[0].strip("<> ")
    return codes


def size_key(s):
    s = str(s)
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]
    return (0 if nums else 1, nums[0] if nums else 0, s)


def product_type_of(title):
    t = title.upper()
    if re.search(r"\b(JACKET|COAT|VEST|GILET|HOODIE|CARDIGAN|SWEATER|PONCHO)\b", t):
        return "Apparel"
    if re.search(r"\b(BAG|BACKPACK|TOTE|PENDANT|KEY ?RING|SCARF|BEANIE|GLOVE|MITTEN|HAT|CAP|EARMUFF)\b", t):
        return "Accessories"
    return "Footwear"


def build_product(code, items):
    first = items[0]
    name = str(first.get("name") or "").strip().upper()
    if not name.startswith("UGG") and not name.startswith("KIDS"):
        name = f"UGG {name}"
    title = f"{name} ({code})"
    ptype = product_type_of(title)
    kg, rule = classify(title, ptype, [code])

    pk, _ = pick(first, PRICE_KEYS)
    dk, desc = pick(first, DESC_KEYS)
    body = (str(desc).strip() if desc else "") + SIZE_GUIDE

    variants, seen, images = [], set(), []
    for it in items:
        sku = str(it.get("sku") or "").strip()
        color = str(it.get("color") or "").strip().upper() or "DEFAULT"
        size = str(it.get("auSize") or it.get("euSize") or "").strip() or "FREE"
        if not sku or (color, size) in seen:
            continue
        seen.add((color, size))
        base = to_float(it.get(pk)) if pk else None
        price = round(base * PRICE_MULTIPLIER, 2) if base else None
        variants.append({"option1": color, "option2": size, "sku": sku, "barcode": sku,
                         "price": f"{price:.2f}" if price else None,
                         "inventory_management": "shopify", "inventory_policy": "deny",
                         "weight": kg, "weight_unit": "kg", "_base": base})
        img = str(it.get("imageUrl") or "").strip()
        if img.startswith("http") and img not in images:
            images.append(img)

    variants.sort(key=lambda v: (v["option1"], size_key(v["option2"])))
    return {
        "title": title, "body_html": body, "vendor": VENDOR, "product_type": ptype,
        "tags": code, "status": "active",
        "options": [{"name": "Color"}, {"name": "Size"}],
        "variants": variants, "images": [{"src": u} for u in images[:20]],
        "_meta": {"price_key": pk, "desc_key": dk, "kg": kg, "weight_rule": rule},
    }


def create_product(headers, domain, prod):
    payload = {k: v for k, v in prod.items() if not k.startswith("_")}
    payload["variants"] = [{k: v for k, v in x.items() if not k.startswith("_") and v is not None}
                           for x in prod["variants"]]
    r = requests.post(f"https://{domain}/admin/api/{API_VERSION}/products.json",
                      headers=headers, json={"product": payload}, timeout=120)
    if r.status_code not in (200, 201) and payload.get("images"):
        # 이미지 주소 문제로 실패하면 이미지 없이 다시 등록
        log(f"   이미지 포함 등록 실패({r.status_code}) -> 이미지 없이 다시 시도: {r.text[:200]}")
        payload.pop("images", None)
        r = requests.post(f"https://{domain}/admin/api/{API_VERSION}/products.json",
                          headers=headers, json={"product": payload}, timeout=120)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"{r.status_code} {r.text[:500]}")
    return r.json()["product"]


def set_stock(headers, domain, location_id, inventory_item_id, qty):
    r = requests.post(f"https://{domain}/admin/api/{API_VERSION}/inventory_levels/set.json",
                      headers=headers, timeout=60,
                      json={"location_id": location_id, "inventory_item_id": inventory_item_id,
                            "available": qty})
    return r.status_code == 200


# ------------------------------------------------------------ main
def main():
    log(f"모드: {MODE}   대상 코드: {', '.join(CODES) or '(없음)'}")
    if not CODES:
        log("CODES 가 비었습니다.")
        return 1

    tok = get_ozwear_token()
    access = get_shopify_access_token()
    if not tok or not access:
        log("토큰 발급 실패 (시크릿 확인)")
        return 1
    domain = os.environ["SHOPIFY_STORE"].replace("https://", "").strip("/")
    headers = {"X-Shopify-Access-Token": access, "Content-Type": "application/json"}

    # 가격 기준 확인: 기존 상품의 API 가격 x 배수 == Shopify 가격 인지
    ref = api_products_by_code(tok, REF_CODE)
    if ref:
        log(f"\n[API 원본 필드 예시: {REF_CODE}]")
        log(json.dumps(ref[0], ensure_ascii=False, indent=2)[:3000])
        pk, pv = pick(ref[0], PRICE_KEYS)
        r = requests.get(f"https://{domain}/admin/api/{API_VERSION}/products.json?limit=250"
                         f"&vendor={requests.utils.quote(VENDOR)}&fields=title,variants", headers=headers, timeout=60)
        shop_price = None
        for p in r.json().get("products", []):
            if p.get("title", "").upper().endswith(f"({REF_CODE})"):
                shop_price = p["variants"][0]["price"]
        calc = round(to_float(pv) * PRICE_MULTIPLIER, 2) if to_float(pv) else None
        log(f"\n가격 기준 확인 {REF_CODE}: API {pk}={pv} x {PRICE_MULTIPLIER} = {calc}  /  Shopify 현재 {shop_price}")
        if shop_price and calc and abs(float(shop_price) - calc) > 0.05:
            log("⚠️ 계산 가격이 Shopify 가격과 다릅니다. 가격 규칙 확인 필요 (apply 시 가격은 그대로 계산값 사용)")
    else:
        log(f"(가격 기준 상품 {REF_CODE} 을 API에서 못 찾음)")

    existing = shopify_codes(headers, domain)
    location_id = get_shopify_location_id(headers, domain) if MODE == "apply" else None

    made, skipped, missing = [], [], []
    for code in CODES:
        log(f"\n■ {code}")
        if code in existing:
            log("   이미 Shopify에 있음 -> 건너뜀")
            skipped.append(code)
            continue
        items = api_products_by_code(tok, code)
        if not items:
            log("   오즈웨어 API에 없음 (단종 또는 코드 다름)")
            missing.append(code)
            continue
        prod = build_product(code, items)
        stock = api_stock(tok, [v["sku"] for v in prod["variants"]])
        m = prod["_meta"]
        colors = sorted({v["option1"] for v in prod["variants"]})
        sizes = sorted({v["option2"] for v in prod["variants"]}, key=size_key)
        prices = sorted({v["price"] for v in prod["variants"] if v["price"]})
        log(f"   제목: {prod['title']}")
        log(f"   유형: {prod['product_type']}   무게: {m['kg']}kg ({m['weight_rule']})")
        log(f"   색상: {', '.join(colors)}")
        log(f"   사이즈: {', '.join(sizes)}")
        log(f"   옵션 {len(prod['variants'])}개 / 가격 {', '.join(prices) or '없음(가격 필드 못 찾음)'} / 재고 합계 {sum(stock.values())}")
        log(f"   이미지 {len(prod['images'])}장 / 설명 필드: {m['desc_key'] or '없음'}")
        if not prices:
            log("   ⚠️ 가격을 못 찾아서 등록하지 않음")
            missing.append(code)
            continue
        if MODE != "apply":
            made.append(code)
            continue
        try:
            created = create_product(headers, domain, prod)
        except Exception as e:
            log(f"   ❌ 등록 실패: {e}")
            missing.append(code)
            continue
        ok = 0
        for v in created.get("variants", []):
            q = stock.get(str(v.get("sku", "")).strip(), 0)
            if location_id and set_stock(headers, domain, location_id, v["inventory_item_id"], q):
                ok += 1
            time.sleep(0.3)
        log(f"   ✅ 등록 완료 (상품ID {created['id']}, 재고 입력 {ok}/{len(created.get('variants', []))})")
        made.append(code)
        time.sleep(0.5)

    log("\n===== 요약 =====")
    log(f"{'등록 완료' if MODE == 'apply' else '등록 예정'} {len(made)}개: {', '.join(made)}")
    log(f"이미 있음 {len(skipped)}개: {', '.join(skipped)}")
    log(f"등록 못 함 {len(missing)}개: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        save_report()
    sys.exit(code)
