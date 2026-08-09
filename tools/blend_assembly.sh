#!/bin/sh
# STL → 色とカメラの付いた .blend。**Blender の Python でないと動かない**ので
# 母艦の .venv ではなくこちらから呼ぶ。引数はそのまま渡る（既定は left right）。
set -e
BLENDER=${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}
exec "$BLENDER" -b -P "$(dirname "$0")/blend_assembly.py" -- "$@"
