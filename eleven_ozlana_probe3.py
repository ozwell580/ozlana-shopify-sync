"""11번가 카테고리·등록 예제 조회 (읽기만 함)"""
import io
import zipfile

import requests

import eleven_api_stock_sync as A

KNOWN = ["10474", "10475", "10471", "123517", "10503", "10504", "10506", "943273", "943275", "123617", "123618"]
WORDS = ["무스탕", "베스트", "조끼", "코트", "점퍼", "재킷", "자켓", "퍼"]


def main():
    api = A.Eleven()
    r = api.req("GET", "/cateservice/category")
    root = A.parse(r)
    cats = {}
    for c in root.iter("category"):
        cats[c.findtext("dispNo")] = (c.findtext("dispNm"), c.findtext("parentDispNo"), c.findtext("leafYn"))
    print("카테고리 수", len(cats))

    def path(no):
        out = []
        while no and no != "0" and no in cats:
            out.append(cats[no][0])
            no = cats[no][1]
        return ">".join(reversed(out))

    for k in KNOWN:
        print("기존", k, path(k))
    for no, (nm, par, leaf) in cats.items():
        p = path(no)
        if p.startswith("해외직구") and "여성" in p and leaf == "Y" and any(w in p for w in WORDS):
            print("후보", no, p)

    for u in ["http://openapi.11st.co.kr/example/multiOption2-1.txt", "http://openapi.11st.co.kr/example/multiOption3.txt"]:
        try:
            t = requests.get(u, timeout=30)
            print("\n=====", u, t.status_code)
            print(t.content.decode("euc-kr", errors="replace")[:5000])
        except Exception as e:
            print(u, e)
    try:
        z = requests.get("https://openapi.11st.co.kr/example/ProductExample1705.zip", timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(z.content))
        print("\n===== zip 목록", zf.namelist())
        for n in zf.namelist():
            if n.lower().endswith((".txt", ".xml")):
                data = zf.read(n)
                txt = data.decode("euc-kr", errors="replace")
                print(f"\n----- {n} ({len(txt)})")
                print(txt[:3500])
                break
    except Exception as e:
        print("zip 실패", e)


if __name__ == "__main__":
    main()
