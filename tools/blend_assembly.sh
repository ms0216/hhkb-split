#!/bin/sh
# STL → 色とカメラの付いた .blend。**Blender の Python でないと動かない**ので
# 母艦の .venv ではなくこちらから呼ぶ。引数はそのまま渡る（既定は left right）。
#
# ⚠️ **Blender は -P のスクリプトが例外で落ちても 0 を返す**（2026-08-12）。
# blend_assembly.py の import が壊れて .blend が 1 つも作られなかったのに、
# ここも refresh_view.sh も成功として抜け、**古い .blend を「出し直した」と
# 報告した。**戻り値では判定できないので、**出来た物を見て**判定する。
set -e
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HALVES=${*:-"left right"}
"$BLENDER" -b -P "$(dirname "$0")/blend_assembly.py" -- $HALVES
# **出来た物を確かめる。**tools/*.py より新しくなければ、作られていない。
NEWEST=$(ls -t "$ROOT"/tools/*.py | head -1)
for h in $HALVES; do
    f="$ROOT/build/assembly/$h.blend"
    if [ ! -f "$f" ] || [ "$f" -ot "$NEWEST" ]; then
        echo "NG $h: $f が作られていない（または $NEWEST より古い）" >&2
        echo "   Blender の出力に例外が出ていないか見ること。" >&2
        exit 1
    fi
done
