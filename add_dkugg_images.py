"""
DK UGG 상품 이미지 자동 등록 (드랍박스 -> Shopify 직접 업로드)

- dkugg_dropbox_links.csv (code, handle, dropbox_link, api_image) 를 읽음
- 드랍박스 공유 폴더 링크를 dl=1 로 바꿔 ZIP으로 받고, 안의 이미지를 전부 꺼냄
- 이미지는 최대 2048px JPG로 줄인 뒤 Shopify staged upload 로 직접 올림 (GitHub 호스팅 불필요)
- 파일 경로/이름에 색상명이 들어 있으면 그 색상 옵션(variant)에 대표 이미지로 연결함
- DK UGG API 대표 이미지를 항상 맨 앞(대표 사진)에 두고, 드랍박스 이미지는 그 뒤에 붙임
  (API 사진과 거의 같은 드랍박스 사진은 중복이라 자동으로 뺌)
- 이미 이미지가 있는 상품은 건너뜀 (여러 번 돌려도 중복 안 생김)
- DKUGG_REPLACE=1 이면 기존 이미지를 지우고 다시 올림 (DKUGG_CODES와 같이 쓰는 걸 권장)

환경변수:
  SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET  (Client Credentials Grant, main.py와 동일)
  SHOPIFY_STORE      기본값 ugg-aus.myshopify.com
  DKUGG_CODES        테스트용: 쉼표로 코드 지정 (예: DK004A,DB017). 비우면 전체
  DKUGG_LIMIT        처리할 최대 상품 수 (0 = 제한 없음)
  DKUGG_MAX_IMAGES   상품당 최대 이미지 수 (기본 12, API 대표 사진 포함)
  DKUGG_REPLACE      1 이면 기존 이미지 삭제 후 다시 등록
"""

import csv
import io
import os
import re
import sys
import time
import zipfile

import requests
from PIL import Image

STORE = os.environ.get("SHOPIFY_STORE", "ugg-aus.myshopify.com").strip()
CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
API_VERSION = "2025-07"
CODES = [c.strip().upper() for c in os.environ.get("DKUGG_CODES", "").split(",") if c.strip()]
LIMIT = int(os.environ.get("DKUGG_LIMIT") or 0)
MAX_IMAGES = int(os.environ.get("DKUGG_MAX_IMAGES") or 12)
REPLACE = (os.environ.get("DKUGG_REPLACE") or "0").strip() in ("1", "true", "yes")
LINKS_CSV = os.environ.get("DKUGG_LINKS_CSV", "dkugg_dropbox_links.csv")

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
MAX_PX = 2048


# ---------------------------------------------------------------- Shopify
def get_token():
    r = requests.post(
        f"https://{STORE}/admin/oauth/access_token",
        data={"grant_type": "client_credentials",
              "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


class Shopify:
    def __init__(self, token):
        self.url = f"https://{STORE}/admin/api/{API_VERSION}/graphql.json"
        self.headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    def gql(self, query, variables=None):
        for attempt in range(5):
            r = requests.post(self.url, headers=self.headers,
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

    def product_by_handle(self, handle):
        q = """
        query($q: String!) {
          products(first: 1, query: $q) {
            nodes {
              id handle title
              media(first: 100) { nodes { id } }
              variants(first: 250) { nodes { id selectedOptions { name value } } }
            }
          }
        }"""
        nodes = self.gql(q, {"q": f"handle:{handle}"})["products"]["nodes"]
        return nodes[0] if nodes and nodes[0]["handle"] == handle else None

    def delete_media(self, product_id, media_ids):
        if not media_ids:
            return
        q = """
        mutation($pid: ID!, $ids: [ID!]!) {
          productDeleteMedia(productId: $pid, mediaIds: $ids) {
            deletedMediaIds
            mediaUserErrors { field message }
          }
        }"""
        res = self.gql(q, {"pid": product_id, "ids": media_ids})["productDeleteMedia"]
        if res["mediaUserErrors"]:
            raise RuntimeError(res["mediaUserErrors"])

    def staged_upload(self, filename, content):
        q = """
        mutation($input: [StagedUploadInput!]!) {
          stagedUploadsCreate(input: $input) {
            stagedTargets { url resourceUrl parameters { name value } }
            userErrors { field message }
          }
        }"""
        res = self.gql(q, {"input": [{
            "filename": filename, "mimeType": "image/jpeg",
            "resource": "IMAGE", "httpMethod": "POST",
            "fileSize": str(len(content)),
        }]})["stagedUploadsCreate"]
        if res["userErrors"]:
            raise RuntimeError(res["userErrors"])
        t = res["stagedTargets"][0]
        form = {p["name"]: p["value"] for p in t["parameters"]}
        up = requests.post(t["url"], data=form,
                           files={"file": (filename, content, "image/jpeg")}, timeout=120)
        if up.status_code not in (200, 201, 204):
            raise RuntimeError(f"staged upload 실패 {up.status_code}: {up.text[:200]}")
        return t["resourceUrl"]

    def create_media(self, product_id, sources, alt):
        q = """
        mutation($pid: ID!, $media: [CreateMediaInput!]!) {
          productCreateMedia(productId: $pid, media: $media) {
            media { id status }
            mediaUserErrors { field message }
          }
        }"""
        media = [{"originalSource": s, "mediaContentType": "IMAGE", "alt": alt} for s in sources]
        res = self.gql(q, {"pid": product_id, "media": media})["productCreateMedia"]
        if res["mediaUserErrors"]:
            print(f"    미디어 오류: {res['mediaUserErrors']}")
        return [m["id"] for m in res["media"] or []]

    def wait_ready(self, product_id, media_ids, timeout=90):
        q = """
        query($id: ID!) {
          product(id: $id) { media(first: 50) { nodes { id status } } }
        }"""
        end = time.time() + timeout
        while time.time() < end:
            nodes = self.gql(q, {"id": product_id})["product"]["media"]["nodes"]
            st = {n["id"]: n["status"] for n in nodes}
            if all(st.get(m) in ("READY", "FAILED") for m in media_ids):
                return st
            time.sleep(3)
        return {}

    def attach_variant_media(self, product_id, pairs):
        if not pairs:
            return
        q = """
        mutation($pid: ID!, $vm: [ProductVariantAppendMediaInput!]!) {
          productVariantAppendMedia(productId: $pid, variantMedia: $vm) {
            userErrors { field message }
          }
        }"""
        vm = [{"variantId": v, "mediaIds": [m]} for v, m in pairs]
        res = self.gql(q, {"pid": product_id, "vm": vm})["productVariantAppendMedia"]
        if res["userErrors"]:
            print(f"    색상 연결 오류: {res['userErrors']}")


# ---------------------------------------------------------------- 이미지 준비
def dropbox_direct(link):
    if not link:
        return ""
    link = re.sub(r"([?&])dl=0", r"\1dl=1", link)
    if "dl=1" not in link:
        link += ("&" if "?" in link else "?") + "dl=1"
    return link


def to_jpeg(raw):
    img = Image.open(io.BytesIO(raw))
    img = img.convert("RGB")
    img.thumbnail((MAX_PX, MAX_PX))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def images_from_dropbox(link):
    url = dropbox_direct(link)
    if not url:
        return []
    r = requests.get(url, timeout=300, allow_redirects=True)
    if r.status_code != 200:
        print(f"    드랍박스 응답 {r.status_code}")
        return []
    data = r.content
    files = []
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in sorted(z.namelist(), key=natural_key):
                base = os.path.basename(name)
                if base.startswith((".", "__")) or not name.lower().endswith(IMG_EXT):
                    continue
                files.append((name, z.read(name)))
    elif r.headers.get("Content-Type", "").startswith("image/"):
        files.append(("image.jpg", data))
    return files


def image_from_api(url):
    if not url:
        return []
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/"):
            return [("api.jpg", r.content)]
    except Exception as e:
        print(f"    API 이미지 실패: {e}")
    return []


def ahash(raw, size=48):
    """중복 사진 판별용 지문: 가로세로 비율 + 48x48 컬러 축소본"""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    ratio = img.width / img.height if img.height else 0
    return ratio, img.resize((size, size)).tobytes()


def is_similar(h1, h2, max_diff=3.0):
    """거의 똑같은 사진만 중복으로 판단 (비율이 같고, 픽셀 평균 차이가 아주 작을 때)"""
    (r1, b1), (r2, b2) = h1, h2
    if abs(r1 - r2) > 0.02:
        return False
    diff = sum(abs(a - b) for a, b in zip(b1, b2)) / len(b1)
    return diff <= max_diff


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ---------------------------------------------------------------- 메인
def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET 시크릿이 없습니다.")
        return 1

    shop = Shopify(get_token())
    rows = list(csv.DictReader(open(LINKS_CSV, encoding="utf-8-sig")))
    if CODES:
        rows = [r for r in rows if r["code"].upper() in CODES]
    if LIMIT:
        rows = rows[:LIMIT]

    stats = {"done": 0, "skip_has_image": 0, "not_found": 0, "no_image": 0, "error": 0}
    failed = []

    for i, row in enumerate(rows, 1):
        code, handle = row["code"], row["handle"]
        print(f"[{i}/{len(rows)}] {code}")
        try:
            product = shop.product_by_handle(handle)
            if not product:
                print("    Shopify에 상품 없음 (임포트 확인 필요)")
                stats["not_found"] += 1
                failed.append((code, "상품 없음"))
                continue
            existing = [m["id"] for m in product["media"]["nodes"]]
            if existing and not REPLACE:
                print("    이미 이미지 있음 - 건너뜀")
                stats["skip_has_image"] += 1
                continue
            if existing and REPLACE:
                shop.delete_media(product["id"], existing)
                print(f"    기존 이미지 {len(existing)}장 삭제")

            # 1) API 대표 사진을 맨 앞에
            api_files = image_from_api(row.get("api_image", ""))
            api_hash = None
            if api_files:
                try:
                    api_hash = ahash(api_files[0][1])
                except Exception:
                    api_hash = None

            # 2) 드랍박스 사진은 뒤에 (API 사진과 같은 사진은 제외)
            dbx_files, dup = [], 0
            for name, raw in images_from_dropbox(row.get("dropbox_link", "")):
                if api_hash is not None:
                    try:
                        if is_similar(api_hash, ahash(raw)):
                            dup += 1
                            continue
                    except Exception:
                        pass
                dbx_files.append((name, raw))

            files = (api_files + dbx_files)[:MAX_IMAGES]
            source = f"API {len(api_files)}장 + 드랍박스 {min(len(dbx_files), MAX_IMAGES - len(api_files))}장"
            if dup:
                source += f" (중복 {dup}장 제외)"
            if not files:
                print("    이미지 못 찾음")
                stats["no_image"] += 1
                failed.append((code, "이미지 없음"))
                continue

            # 색상별 variant 목록
            color_variants = {}
            for v in product["variants"]["nodes"]:
                for o in v["selectedOptions"]:
                    if o["name"].lower() == "color":
                        color_variants.setdefault(o["value"], []).append(v["id"])

            sources, names = [], []
            for idx, (name, raw) in enumerate(files, 1):
                try:
                    jpg = to_jpeg(raw)
                except Exception as e:
                    print(f"    이미지 변환 실패 {name}: {e}")
                    continue
                sources.append(shop.staged_upload(f"{handle}-{idx}.jpg", jpg))
                names.append(name)

            media_ids = shop.create_media(product["id"], sources, product["title"])
            print(f"    이미지 {len(media_ids)}장 등록: {source}")

            # 파일 경로에 색상명이 있으면 해당 색상 옵션에 연결 (색상별 첫 이미지)
            pairs, used = [], set()
            if color_variants and media_ids:
                st = shop.wait_ready(product["id"], media_ids)
                for name, mid in zip(names, media_ids):
                    if st and st.get(mid) != "READY":
                        continue
                    n = norm(name)
                    # 긴 색상명부터 비교 (예: "Light Grey"가 "Grey"보다 먼저)
                    for color in sorted(color_variants, key=len, reverse=True):
                        if color in used or not norm(color):
                            continue
                        if norm(color) in n:
                            pairs += [(vid, mid) for vid in color_variants[color]]
                            used.add(color)
                            break
                shop.attach_variant_media(product["id"], pairs)
                if used:
                    print(f"    색상 연결: {sorted(used)}")
            stats["done"] += 1
        except Exception as e:
            print(f"    오류: {e}")
            stats["error"] += 1
            failed.append((code, str(e)[:120]))

    print("\n" + "=" * 50)
    print(f"완료 {stats['done']} / 이미 있음 {stats['skip_has_image']} / "
          f"상품 없음 {stats['not_found']} / 이미지 없음 {stats['no_image']} / 오류 {stats['error']}")
    for code, why in failed:
        print(f"  - {code}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
