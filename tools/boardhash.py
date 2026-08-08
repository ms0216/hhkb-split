"""基板の「設計としての中身」を指紋にする。

**バイト列の sha256 は使えない。** KiCad は保存のたびに UUID を振り直し、
フットプリントの書き出し順も変える。設計が同じでもバイト列は毎回変わる
（実測で確認）。

ここでは並び順と UUID を落とし、**配置と結線だけ**を取り出して
ハッシュする。同じ設計なら何度保存しても同じ値になり、部品が 0.1mm
動けば変わる。

pcbnew を使わない（S 式のテキストとして読む）ので、通常の venv から走る。
"""

import hashlib
import re

FP = re.compile(r'\n\t\(footprint "([^"]+)"')
AT = re.compile(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)")
REF = re.compile(r'\(property "Reference" "([^"]+)"')
PAD = re.compile(r'\(pad "([^"]*)"[\s\S]{0,400}?\(net \d+ "([^"]*)"\)')
EDGE = re.compile(r'\(gr_(line|arc)\b([\s\S]{0,300}?)\(layer "Edge\.Cuts"\)')
XY = re.compile(r"\((?:start|mid|end) ([-\d.]+) ([-\d.]+)\)")


def _blocks(txt):
    """フットプリントを括弧の対応で切り出す。"""
    for m in FP.finditer(txt):
        i = m.start() + 1
        depth, j = 0, i
        while True:
            if txt[j] == "(":
                depth += 1
            elif txt[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.group(1), txt[i:j + 1]


def canonical(txt):
    """並び順と UUID を落とした、設計の正規形。"""
    rows = []
    for name, blk in _blocks(txt):
        r, a = REF.search(blk), AT.search(blk)
        if not (r and a):
            continue
        pads = sorted((n, net) for n, net in PAD.findall(blk))
        rows.append((r.group(1), name,
                     f"{float(a.group(1)):.4f}", f"{float(a.group(2)):.4f}",
                     f"{float(a.group(3) or 0):.2f}", tuple(pads)))
    edges = sorted(
        (kind,) + tuple(f"{float(x):.4f},{float(y):.4f}"
                        for x, y in XY.findall(body))
        for kind, body in EDGE.findall(txt))
    return repr((sorted(rows), edges))


def fingerprint(path):
    """配置・結線・外形から決まる 64 桁の指紋。"""
    with open(path) as f:
        return hashlib.sha256(canonical(f.read()).encode()).hexdigest()
