"""
오즈라나 쿠키 컬렉션 신상품 3개(OZ3035, OZ1041, OZ0033)의 이미지를
Dropbox 공유 폴더에서 zip으로 통째로 다운로드한 뒤, Shopify 상품에 직접 첨부합니다.
(GitHub 업로드 단계 없이 base64로 바로 첨부하는 방식)
main.py와 같은 저장소(ozlana-shopify-sync)에 넣고 실행하세요.

사용법:
    python add_ozlana_cookie_images.py
"""

import base64
import io
import zipfile

import requests

from main import get_shopify_access_token, SHOPIFY_STORE

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

PRODUCTS = [
    {
        "code": "OZ3035",
        "product_id": 8717754925241,
        "dropbox_url": "https://www.dropbox.com/scl/fo/6vws7ea71s3uk431ck5s3/APRGODWNZYMvVXVKZMxffXI?rlkey=cl2va1ec6n6q0snkny67ozu71&st=491u32iv&dl=0",
    },
    {
        "code": "OZ1041",
        "product_id": 8717754990777,
        "dropbox_url": "https://www.dropbox.com/scl/fo/abifqpmdzkca1x6bw1hec/AO-qdFhENvlF4bj4RyrjTm8?rlkey=ygx90qf1ae0h4opeunhcvxo6d&st=ydwctqi6&dl=0",
    },
    {
        "code": "OZ0033",
        "product_id": 8717755056313,
        "dropbox_url": "https://www.dropbox.com/scl/fo/0zzfvz171pzlc0f342us2/ALQaVEPEQPbzlUuOwy2vXqc?rlkey=gnyfdr4pqxh719p7si0uld0xw&st=8e30fgmj&dl=0",
    },
]


def to_zip_url(dropbox_url):
    # 공유 폴더 링크를 zip 다운로드 링크로 변환 (dl=0 -> dl=1)
    if "dl=0" in dropbox_url:
        return dropbox_url.replace("dl=0", "dl=1")
    if "dl=1" in dropbox_url:
        return dropbox_url
    sep = "&" if "?" in dropbox_url else "?"
    return dropbox_url + sep + "dl=1"


def download_images(dropbox_url):
    zip_url = to_zip_url(dropbox_url)
    res = requests.get(zip_url, timeout=120)
    res.raise_for_status()

    images = []
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        for name in sorted(zf.namelist()):
            if name.lower().endswith(IMAGE_EXTS) and "__MACOSX" not in name:
                images.append((name, zf.read(name)))
    return images


def attach_image(shopify_headers, store_domain, product_id, filename, data, position):
    url = f"https://{store_domain}/admin/api/2024-01/products/{product_id}/images.json"
    payload = {
        "image": {
            "attachment": base64.b64encode(data).decode("utf-8"),
            "filename": filename,
            "position": position,
        }
    }
    res = requests.post(url, headers=shopify_headers, json=payload)
    return res.status_code in (200, 201), res.text if res.status_code not in (200, 201) else "ok"


def main():
    access_token = get_shopify_access_token()
    if not access_token:
        print("Shopify 토큰 발급 실패")
        return

    shopify_headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    store_domain = SHOPIFY_STORE.replace("https://", "").strip("/")

    for item in PRODUCTS:
        print(f"\n===== {item['code']} =====")
        try:
            images = download_images(item["dropbox_url"])
        except Exception as e:
            print(f"[다운로드 실패] {item['code']} - {e}")
            continue

        print(f"이미지 {len(images)}개 다운로드 완료: {[n for n, _ in images]}")

        if not images:
            print("첨부할 이미지가 없습니다 (zip 안에 이미지 파일 없음)")
            continue

        for idx, (filename, data) in enumerate(images, start=1):
            ok, info = attach_image(
                shopify_headers, store_domain, item["product_id"], filename, data, idx
            )
            if ok:
                print(f"[첨부 완료] {filename} (position {idx})")
            else:
                print(f"[첨부 실패] {filename} - {info}")


if __name__ == "__main__":
    main()
