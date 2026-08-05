"""採寸に使う参照資料をすべて再取得する。

参照画像は著作物なのでリポジトリには含めない（`build/` は .gitignore 済み）。
代わりにこのスクリプトが「どこから何を取ったか」を保持し、いつでも同じ状態を
再現できるようにする。採寸結果を検証したくなったら、まずこれを実行する。

    .venv/bin/python tools/fetch_references.py          # 全部取得
    .venv/bin/python tools/fetch_references.py --list   # 一覧だけ表示

出典と用途は docs/hardware/reference-sources.md にも記述してある。
"""

import argparse
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "build" / "photos"
UA = "hhkb-split-research/1.0 (personal design reference)"

# ---------------------------------------------------------------------------
# 直接 URL が分かっている資料
# ---------------------------------------------------------------------------

DIRECT = [
    {
        "id": "qmk_hhkb_ansi.json",
        "url": "https://raw.githubusercontent.com/qmk/qmk_firmware/master/keyboards/hhkb/ansi/info.json",
        "purpose": "キー配置の一次情報。実機 HHKB 用置換コントローラ(Hasu版)のレイアウト定義。"
                   "最下段の x/w がここで確定する",
        "license": "QMK Firmware / GPL-2.0",
        "dest": "../qmk_hhkb_ansi.json",
    },
    {
        "id": "pfu_safety_manual.pdf",
        "url": "https://origin.pfultd.com/downloads/hhkb/manual/P3PC-6631-08XA.pdf",
        "purpose": "PFU 公式マニュアル。寸法図は無かったが、規制モデル名 PD-KB800 の確認に使える",
        "license": "PFU Limited (c)",
        "dest": "../pfu_safety_manual.pdf",
    },
]

# PFU 公式解説記事「キーキャップのプロファイルと種類・印字方法について解説」
# https://happyhackingkb.com/jp/life/hhkb_life76.html
# 画像は images/hhkb_life76-N.webp (N=1..30)
PFU_LIFE76 = {
    "base": "https://happyhackingkb.com/jp/life/images/hhkb_life76-{n}.webp",
    "range": range(1, 31),
    "dir": "pfu_life76",
    "license": "PFU Limited (c) — 私的な採寸参照のみ。再配布しない",
    "key_images": {
        "hhkb_life76-16": "★ 全体の真横写真。5列すべてのキーキャップと側面が写る。段差と角度の実測に使う",
        "hhkb_life76-18": "真横写真(別カット)。相互検証用",
        "hhkb_life76-9": "白モデルの真横写真＋シリンダー曲線の注釈。相互検証用",
        "hhkb_life76-20": "白モデルの真横写真。相互検証用",
        "hhkb_life76-24": "★ キーキャップ断面の技術線画。側面6種＋正面6種。列ごとの傾き角",
        "hhkb_life76-11": "列プロファイル記号(R1〜R4)付きの配列図",
        "hhkb_life76-15": "Low / Standard(Cherry相当) / Hi Profile の高さ比較図",
        "hhkb_life76-10": "最下段付近のキーキャップ側面アップ",
    },
}

# pdweb.jp のレビュー記事(HHKB Professional BT)
# http://www.pdweb.jp/column/c_md/c_md97.shtml
PDWEB = {
    "bases": [
        "http://www.pdweb.jp/column/c_md/md97/97_{n}_s.jpg",   # サムネイル
        "http://www.pdweb.jp/column/c_md/md97/97_{n}.jpg",      # 大きい版(存在しない番号あり)
    ],
    "range": [f"{i:02d}" for i in range(12)],
    "dir": "pdweb",
    "license": "pdweb.jp (c) — 私的な採寸参照のみ。再配布しない",
    "key_images": {
        "97_03": "★ 背面。電池ボックス(単三×2)・電源スイッチ・USB 端子の位置と注釈",
        "97_07": "底面。チルト脚の機構",
        "97_05": "側面(注釈付き)",
        "97_11": "斜め(注釈付き)",
    },
}

# ---------------------------------------------------------------------------
# Wikimedia Commons（API で URL を解決してから取得する）
# ---------------------------------------------------------------------------

COMMONS_TITLES = {
    "HHKB Pro Hybrid Type-S.jpg":
        "★ 実機 HYBRID Type-S をほぼ真上から撮影(3829x1565)。鍵盤面の幅の検証に使用",
    "HHKB Pro 2 - keyboard layout editor - final.png":
        "★ HHKB Pro 2 の KLE 図(刻印つき)。キー配置と Fn 面の対応表の一次情報",
    "Happy Hacking Keyboard Professional 2.jpg": "俯瞰写真。配列の目視確認",
    "HHKB Pro JP Type-S keyboard case.jpg": "分解写真。ケース上半分とプレート",
    "HHKB Pro JP Type-S keyboard case reverse side.jpg": "分解写真。ケース内側",
    "HHKB Pro JP Type-S PCB.jpg": "分解写真。基板",
}
COMMONS_LICENSE = "Wikimedia Commons — 個々のファイルのライセンス表記に従うこと"


def run_curl(url, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", "90", "-A", UA, "-o", str(out_path), url],
        capture_output=True,
    )
    ok = r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 2000
    if not ok and out_path.exists():
        out_path.unlink()
    return ok


def resolve_commons(titles):
    """Commons のファイル名から実 URL を引く。"""
    q = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "titles": "|".join(f"File:{t}" for t in titles),
        }
    )
    out = subprocess.run(
        ["curl", "-sSL", "--max-time", "60", "-A", UA,
         f"https://commons.wikimedia.org/w/api.php?{q}"],
        capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    result = {}
    for p in data.get("query", {}).get("pages", {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("url"):
            result[p["title"].replace("File:", "")] = ii["url"]
    return result


def listing():
    print("== 直接 URL ==")
    for d in DIRECT:
        print(f"  {d['id']}\n     {d['url']}\n     用途: {d['purpose']}\n     出典: {d['license']}")
    print(f"\n== PFU 公式解説記事 (30枚) -> {PFU_LIFE76['dir']}/ ==")
    print(f"   出典: {PFU_LIFE76['license']}")
    for k, v in PFU_LIFE76["key_images"].items():
        print(f"     {k}: {v}")
    print(f"\n== pdweb.jp レビュー (12枚×2版) -> {PDWEB['dir']}/ ==")
    print(f"   出典: {PDWEB['license']}")
    for k, v in PDWEB["key_images"].items():
        print(f"     {k}: {v}")
    print(f"\n== Wikimedia Commons ==\n   出典: {COMMONS_LICENSE}")
    for k, v in COMMONS_TITLES.items():
        print(f"     {k}: {v}")


def fetch_all():
    DEST.mkdir(parents=True, exist_ok=True)
    n_ok = n_ng = 0

    for d in DIRECT:
        p = (DEST / d["dest"]).resolve()
        ok = run_curl(d["url"], p)
        print(f"{'OK ' if ok else 'NG '} {d['id']}")
        n_ok, n_ng = (n_ok + 1, n_ng) if ok else (n_ok, n_ng + 1)

    for n in PFU_LIFE76["range"]:
        url = PFU_LIFE76["base"].format(n=n)
        ok = run_curl(url, DEST / PFU_LIFE76["dir"] / f"hhkb_life76-{n}.webp")
        n_ok, n_ng = (n_ok + 1, n_ng) if ok else (n_ok, n_ng + 1)
    print(f"OK  PFU 公式解説記事 -> {PFU_LIFE76['dir']}/")

    for n in PDWEB["range"]:
        for base in PDWEB["bases"]:
            url = base.format(n=n)
            suffix = "_s" if "_s.jpg" in base else ""
            run_curl(url, DEST / PDWEB["dir"] / f"97_{n}{suffix}.jpg")
    print(f"OK  pdweb.jp -> {PDWEB['dir']}/")

    urls = resolve_commons(COMMONS_TITLES)
    for title, url in urls.items():
        safe = title.replace(" ", "_").replace("/", "_")
        ok = run_curl(url, DEST / "commons" / safe)
        print(f"{'OK ' if ok else 'NG '} commons/{safe}")
        n_ok, n_ng = (n_ok + 1, n_ng) if ok else (n_ok, n_ng + 1)
    missing = set(COMMONS_TITLES) - set(urls)
    if missing:
        print(f"NG  Commons で解決できなかったファイル: {missing}")

    print(f"\n完了: 成功 {n_ok} / 失敗 {n_ng}  -> {DEST}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="取得せず一覧だけ表示する")
    args = ap.parse_args()
    if args.list:
        listing()
    else:
        fetch_all()
    sys.exit(0)
