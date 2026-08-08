"""JLCPCB の部品を調べる。**区分・在庫・単価**を出す。

    .venv/bin/python3 tools/jlcpcb_lookup.py C81598 "100uF 1206" 74HC595
    .venv/bin/python3 tools/jlcpcb_lookup.py --parts     # parts.py の全部品

なぜ道具にしたか
----------------
**ブラウザが要ると思い込んで、見積もりを 3 回外した。**

  「FFC は ¥4,000」→ 数量 1 の価格を 15 個に掛けていた
  「¥1,100 程度」  → まだ外れていた。実際は $0.2635 で 15 個 ¥600
  「100uF 1206 に Basic は無い」→ あった（C15008）

さらに、書いたソケット C5184526 は**在庫 0** だった。発注できない部品を
指定するところだった。**在庫は見ないと分からない。推測は当たらない。**

読み方
------
  Basic        段取り費 $0
  Preferred    段取り費 $0（Extended だが preferredComponentFlag が真）
  Extended $3  **1 種類あたり $3。ここが効く。**部品代の 4 割を占めた

**発注の直前にもう一度走らせること。**在庫も価格も変わる。
"""

import json
import subprocess
import sys
from pathlib import Path

API = ("https://jlcpcb.com/api/overseas-pcb-order/v1/"
       "shoppingCart/smtGood/selectSmtComponentList")


def search(keyword, limit=10):
    """キーワード（型番・C 番号・説明）で引く。

    **curl を使う。**venv の Python は証明書を持っておらず、urllib だと
    CERTIFICATE_VERIFY_FAILED で全部落ちる（実際に落ちた）。
    """
    body = json.dumps({"currentPage": 1, "pageSize": limit,
                       "keyword": keyword, "searchSource": "search"})
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", API,
         "-H", "Content-Type: application/json",
         "-H", "User-Agent: Mozilla/5.0",
         "-H", "Origin: https://jlcpcb.com",
         "-H", "Referer: https://jlcpcb.com/parts",
         "-d", body],
        capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(f"curl が失敗した: {r.stderr[:200]}")
    d = json.loads(r.stdout)
    return (d.get("data") or {}).get("componentPageInfo", {}).get("list", [])


def classify(c):
    """Basic / Preferred / Extended $3。**段取り費はここで決まる。**"""
    if c.get("componentLibraryType") == "base":
        return "Basic"
    return "Preferred" if c.get("preferredComponentFlag") else "Extended $3"


def price_at(c, qty=100):
    for p in c.get("componentPrices") or []:
        if p["startNumber"] <= qty <= (p.get("endNumber") or 10 ** 9):
            return p["productPrice"]
    return None


def show(keyword, limit=10):
    print(f"\n=== {keyword} ===")
    try:
        rows = search(keyword, limit)
    except Exception as e:
        print(f"  引けなかった: {type(e).__name__} {e}")
        return
    if not rows:
        print("  見つからない")
        return
    for c in rows:
        p = price_at(c)
        stock = c.get("stockCount") or 0
        warn = "  ★在庫なし★" if stock == 0 else ""
        print(f"  {c.get('componentCode', ''):>11s} {classify(c):12s} "
              f"在庫{stock:>9,} ${p if p is not None else '?':<9} "
              f"{c.get('componentModelEn')} / "
              f"{(c.get('componentSpecificationEn') or '')[:30]}{warn}")


def main():
    args = [a for a in sys.argv[1:] if a != "--parts"]
    if "--parts" in sys.argv or not args:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from parts import PARTS
        print("tools/parts.py に書いてある番号を、いまの在庫で確かめる")
        for kind, spec in sorted(PARTS.items()):
            code = spec["lcsc"]
            if not code:
                print(f"\n=== {kind} === 番号がまだ無い（{spec['desc']}）")
                continue
            show(f"{kind}: {code}".split(": ")[1], 3)
        return
    for a in args:
        show(a)


if __name__ == "__main__":
    main()
