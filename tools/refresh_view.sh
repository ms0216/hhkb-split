#!/bin/sh
# **CAD を変えたら、これを叩く。**STL を出し直して .blend まで作る。
#
# 2026-08-12 に利用者から出た要望:「CAD を変更したら Blender 出力する癖を
# つけて欲しい」。**癖ではなく手順にする**——覚えておく決まりは守られない。
#
# この案件では実際に、利用者が開いた left.blend が**前日 22:27 のもので、
# その日の変更が 1 つも入っていなかった**（右側は STL 自体が 8 時間前）。
# 絵は設計を目で確かめる道具なので、**古い絵は嘘の検証**になる。
#
# blend_assembly.py は STL が tools/*.py より古ければ止まる（門）。
# ここはその前段（export）も含めて 1 回で済ませるためのもの。
#
#   使い方:  tools/refresh_view.sh            # 両側
#            tools/refresh_view.sh left       # 片側だけ（速い）
set -e
cd "$(dirname "$0")/.."
# 引数が無ければ両側。**`$*` の unquoted 展開ではなく位置パラメータで持つ**
# （空白入りの引数が来ても壊れない）。
if [ $# -eq 0 ]; then
    set -- left right
fi
echo "== STL を出す（$*）"
.venv/bin/python3 tools/export_assembly.py "$@"
echo "== .blend を作る（$*）"
tools/blend_assembly.sh "$@"
echo
echo "開き方: build/assembly/left.blend をダブルクリック。"
