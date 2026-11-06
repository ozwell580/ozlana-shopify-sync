"""오즈라나 중국 창고(55) API 확인용 — 조회만 함"""
import json, os, requests
B = (os.environ.get("OZLANA_BASE_URL") or "http://www.ozlanacms.com.au:30008").rstrip("/")
H = {"X-Token": os.environ["OZLANA_TOKEN"]}
TARGET = {"OZ0035", "OZ0036", "OZ35", "OZ36"}

def call(method, path, params=None):
    try:
        r = requests.request(method, B + path, headers=H, params=params, timeout=120)
        try:
            body = r.json(); d = body.get("data")
            d = json.loads(d) if isinstance(d, str) and d.strip() else d
        except Exception:
            body, d = None, None
        return r.status_code, body, d, r.text
    except Exception as e:
        return "ERR", None, None, str(e)

s, b, d, t = call("POST", "/warehouses"); print("POST /warehouses", s, t[:200])
s, b, d, t = call("GET", "/products")
prods = d or []
print("GET /products", s, "행", len(prods))
hits = [p for p in prods if str(p.get("prodMark", "")).upper().replace(" ", "") in TARGET or "TALL" in str(p.get("prodName", "")).upper()]
for p in hits[:20]:
    print("  상품:", json.dumps(p, ensure_ascii=False))
marks = sorted({str(p.get("prodMark")) for p in prods})
print("  /products 상품코드 수", len(marks))

for wid in (55, "55", 49):
    s, b, d, t = call("GET", "/stocks", {"warehouse_id": wid})
    print(f"GET /stocks warehouse_id={wid!r}", s, "message:", (b or {}).get("message"), "행", len(d or []), "| 원문앞부분", t[:150])

for p in hits[:6]:
    pid = p.get("id")
    for wid in (55, 49):
        s, b, d, t = call("GET", f"/stock/{pid}", {"warehouse_id": wid})
        print(f"GET /stock/{pid}?warehouse_id={wid}", s, t[:300])
        for st in (d or [])[:1]:
            if isinstance(st, dict) and st.get("barCode"):
                s2, _, _, t2 = call("GET", "/stock_by_barcode", {"barcode": st["barCode"], "warehouse_id": wid})
                print(f"   /stock_by_barcode {st['barCode']} wh={wid}", s2, t2[:200])
