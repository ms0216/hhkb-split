#!/bin/sh
# 基板が変わったら、絵を出し直して「見ろ」と突きつける。
#
# 発端（2026-08-16）: 「視覚的に確認した？」に「していません」と答え続けた。
# 道具（kicad-cli・pdftoppm）は前からあった。**呼ぶかどうかが裁量だった**ので
# 呼ばれなかった。ここは裁量の外に置く。
#
# **触ったファイル名では絞らない。**基板を書くのは Write ではなく
# gen_pcb.py / autoroute.py / gen_daughterboard.py（Bash 経由）。
# tool_input.file_path で絞ると本命の経路をまるごと取り逃がす。
# 代わりに毎回 3 枚の指紋を見る（変化が無ければ 0.3 秒で黙って終わる）。

set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$ROOT/.venv/bin/python3"

cat >/dev/null                      # フックへの入力は使わないが、読み捨てる

[ -x "$PY" ] || exit 0              # venv が無い環境では黙る

OUT="$("$PY" "$ROOT/tools/render_pcb.py" --all 2>&1)" || true

# 変わった板と、その拡大図を拾う。全部「変化なし」なら何も言わない。
# **拡大図の行も拾うこと。**`^描いた` だけで絞ると、D_PWR の拡大図が
# 出来ているのに伝わらない（実際にそうなっていた）。拡大図の行は字下げしてある。
DREW="$(printf '%s\n' "$OUT" | grep -E '^(描いた|  拡大)' || true)"
BAD="$(printf '%s\n' "$OUT" | grep '^NG' || true)"

if [ -n "$BAD" ]; then
  printf '%s\n' "$BAD" >&2          # 描けなかった理由は隠さない
fi

[ -n "$DREW" ] || exit 0

printf '%s\n' "$DREW" >&2           # 人の画面にも出す

PNGS="$(printf '%s\n' "$DREW" | awk '{printf "%s ", $NF}')"
"$PY" - "$PNGS" <<'EOF'
import json, sys
pngs = sys.argv[1].split()
# 拡大図は「動いた部品の周り」。全体図では読めないので、まずこれを見る。
zooms = [p for p in pngs if "__" in p]
msg = ["基板が変わったので絵を出し直した:"] + [f"  {p}" for p in pngs]
if zooms:
    msg += ["",
            "**動いた部品の拡大図がある。まずこれを見ること:**"]
    msg += [f"  {p}   （{p.split('__')[-1][:-4]} の周り）" for p in zooms]
msg += ["",
        "**Read でこの PNG を実際に見ること。**"
        "見る前に配線・配置・シルクについて「問題ない」と書かない。"
        "見たなら、絵の中で確かめたことを具体的に書く。"]
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PostToolUse", "additionalContext": "\n".join(msg)}}))
EOF
