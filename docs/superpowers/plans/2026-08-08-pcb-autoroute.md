# 本体基板の配線を自動配線器へ — 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 本体基板 左/右 の配線を手書きルータから Freerouting へ移し、DRC 違反 0・未配線 0 にする。

**Architecture:** `gen_pcb.py` は配置・ネット・ゾーン・設計規則だけを持つ。配線は `autoroute.py` が Specctra DSN/SES の往復で Freerouting に委ねる。部品は「原点」ではなく「コートヤード」を基準に帯へ収める。

**Tech Stack:** KiCad 10.0.5 の pcbnew Python API / OpenJDK 26 / Freerouting v2.3.0 / pytest

設計書: [docs/superpowers/specs/2026-08-08-pcb-autoroute-design.md](../specs/2026-08-08-pcb-autoroute-design.md)

## Global Constraints

- **`tools/interface.py` は凍結境界。**プレート・基板・ケースが共有する。この計画では**一切変更しない**
- **`tools/gen_daughterboard.py` は対象外。**子基板は違反 0。触らない
- **検査は「効いていること」まで見る。**新しい検査は必ず**故意に壊して落ちることを確かめてから**コミットする
- **接頭辞でフットプリントを走査しない。**`re.fullmatch(r"D\d+")` のように絞る。`D` / `SW` で拾うと `D_PWR` / `SW_PWR` を巻き込む（過去 3 回発生）
- **`test_pcb.py` は pcbnew を使わない。**`.kicad_pcb` を S 式のテキストとして読む。この規約を守る（通常の venv から実行されるため）
- 基板の生成は KiCad の Python で: `KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9`
- Java は `/opt/homebrew/opt/openjdk/bin` にある（`PATH` に追加が必要）
- Freerouting: `~/.local/share/freerouting/freerouting-2.3.0.jar`
- 判断の材料は毎回 DRC の JSON。**印象で戻さない**

### 実測済みの数値（この計画の前提）

| | 値 |
|---|---|
| 帯 0 の範囲（KiCad y） | **64.5 – 73.75**（中心 69.125・高さ 9.25mm） |
| `SOIC-16_3.9x9.9mm_P1.27mm` コートヤード | 7.49 × **10.49mm** |
| `TSSOP-16_4.4x5mm_P0.65mm` コートヤード | 7.79 × **5.59mm** |
| 現状の違反 | 左 **25** / 右 **29** / 子基板 0 |

---

### Task 1: 帯からはみ出した部品を検出する検査

**なぜ最初か:** いま `U1` と `J_DB` がはみ出していることを、機械が言える状態にしてから直す。直してから検査を書くと、検査が効いているか確かめられない。

**Files:**
- Create: `tools/bands.py`
- Modify: `tools/gen_pcb.py`（`BAND_Y` の定義を `bands.py` へ移して import）
- Test: `tools/test_pcb.py`（末尾に追加）

**Interfaces:**
- Produces: `bands.BAND_Y: list[float]`（レイアウト座標・4 本）、`bands.BAND_H: float = 9.25`、`bands.band_bounds_kicad(i, origin_y=100.0) -> (y_lo, y_hi)`

- [ ] **Step 1: `tools/bands.py` を作る**

`BAND_Y` を `gen_pcb.py` から切り出す。**pcbnew を import しない**こと（`test_pcb.py` から読めなくなる）。

```python
"""電子部品を置く帯の位置。

**gen_pcb.py と test_pcb.py の両方が使う。** 生成側と検査側で別々に
持つと、片方だけ直したときに静かにずれる。

pcbnew を import しないこと。test_pcb.py は通常の venv から走る。
"""

# ソケットの占有はキー中心に対して非対称（-2.6 〜 +7.2mm）なので、
# 段と段の中間に置くと 0.9mm ソケットに掛かる（実際に掛かって短絡した）。
# ソケットの中心ぶんずらす。
_SOCK_MID = (7.2 + (-2.6)) / 2

# 帯の中心（レイアウト座標・原点中心・Y 上向き）。奥から手前へ 4 本。
BAND_Y = [28.575 + _SOCK_MID, 9.525 + _SOCK_MID,
          -9.525 + _SOCK_MID, -28.575 + _SOCK_MID]

# 段と段の間で部品を置ける高さ。
BAND_H = 9.25


def band_bounds_kicad(i, origin_y=100.0):
    """帯 i の KiCad 座標での範囲 (y_lo, y_hi) を返す。

    KiCad は Y 下向きなので、レイアウト座標から符号が反転する。
    """
    center = origin_y - BAND_Y[i]
    return center - BAND_H / 2, center + BAND_H / 2
```

- [ ] **Step 2: `gen_pcb.py` を `bands.py` から読むように変える**

`gen_pcb.py` の 336–338 行（`_SOCK_MID` と `BAND_Y` の定義）を消し、import に置き換える。**値は変えない。**

```python
from bands import BAND_H, BAND_Y
```

- [ ] **Step 3: 検査を書く（この時点では落ちる）**

`tools/test_pcb.py` の末尾に追加する。`_footprint_blocks` と `_courtyard_bbox` は他の検査からも使えるよう、モジュール直下に置く。

```python
# --------------------------------------------------------------------------
# 電子部品が帯に収まっているか
#
# **「寄っている」と「入っていない」は別の問題。**
# SOIC-16 はコートヤード 10.49mm で、帯 9.25mm にそもそも入らない。
# 位置を微調整しても 0 にはならない。算数で入らないものを、機械が言う。
# --------------------------------------------------------------------------

def _footprint_blocks(txt):
    """(参照名, フットプリントの S 式) を順に返す。括弧の対応で切り出す。"""
    for m in re.finditer(r"\n\t\(footprint ", txt):
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
        blk = txt[i:j + 1]
        r = re.search(r'\(property "Reference" "([^"]+)"', blk)
        if r:
            yield r.group(1), blk


def _courtyard_bbox(blk):
    """コートヤードの世界座標での (x0, y0, x1, y1)。無ければ None。"""
    import math
    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
    ox, oy = float(at.group(1)), float(at.group(2))
    rot = math.radians(float(at.group(3) or 0))
    pts = []
    for m in re.finditer(
            r"\(fp_(line|rect|poly)\b([\s\S]*?)\(layer \"([^\"]+)\"\)", blk):
        if not m.group(3).endswith(".CrtYd"):
            continue
        pts += [(float(a), float(b)) for a, b in
                re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", m.group(2))]
        for tag in ("start", "end"):
            g = re.search(rf"\({tag} ([-\d.]+) ([-\d.]+)\)", m.group(2))
            if g:
                pts.append((float(g.group(1)), float(g.group(2))))
    if not pts:
        return None
    c, s = math.cos(rot), math.sin(rot)
    w = [(ox + x * c - y * s, oy + x * s + y * c) for x, y in pts]
    xs, ys = [p[0] for p in w], [p[1] for p in w]
    return min(xs), min(ys), max(xs), max(ys)


# 電子部品の参照名。**接頭辞で拾わない。**`D` や `SW` で走査すると
# ダイオード 61 個とスイッチ 61 個を巻き込む（過去 3 回やった）。
ELEC_REF = re.compile(r"U\d+|C_[A-Z0-9]+|R_[A-Z]+|D_PWR|SW_PWR|J_DB|BT1_[+-]")


@pytest.mark.parametrize("half", NAMES)
def test_the_electronics_fit_inside_their_band(half):
    """電子部品のコートヤードが帯 9.25mm の内側にあること。

    はみ出していると、行のバスやソケットに当たる。**位置の微調整では
    直らない**（部品そのものが大きい）ので、フットプリントを選び直す
    必要がある。それを人の目に頼らない。
    """
    from bands import BAND_H, band_bounds_kicad
    txt = (PCB / f"hhkb_split_{half}.kicad_pcb").read_text()
    bad = []
    seen = 0
    for ref, blk in _footprint_blocks(txt):
        if not ELEC_REF.fullmatch(ref):
            continue
        bb = _courtyard_bbox(blk)
        assert bb is not None, f"{half}: {ref} にコートヤードが無い"
        seen += 1
        # どの帯に属するかは、部品の中心がいちばん近い帯で決める。
        mid = (bb[1] + bb[3]) / 2
        i = min(range(4), key=lambda k: abs(sum(band_bounds_kicad(k)) / 2 - mid))
        lo, hi = band_bounds_kicad(i)
        if bb[1] < lo - 1e-6 or bb[3] > hi + 1e-6:
            bad.append(f"{ref}: y {bb[1]:.3f}..{bb[3]:.3f} "
                       f"(高さ {bb[3] - bb[1]:.3f}) が帯 {i} "
                       f"{lo:.3f}..{hi:.3f} からはみ出す")
    assert seen >= 10, f"{half}: 電子部品を {seen} 個しか見ていない。走査が壊れている"
    assert not bad, f"{half}: 帯 {BAND_H}mm に収まっていない部品\n" + "\n".join(bad)
```

- [ ] **Step 4: 落ちることを確認する**

```bash
.venv/bin/pytest tools/test_pcb.py -k fit_inside_their_band -q
```

期待: **両方 FAIL。** 出力に以下が含まれること。

```
U1: y 65.725..76.125 (高さ 10.400) が帯 0 64.500..73.750 からはみ出す
J_DB: y 66.125..74.025 (高さ 7.900) が帯 0 64.500..73.750 からはみ出す
```

右は `U1` / `U2` / `J_DB` の 3 件。**この 3 行が出ていなければ検査が壊れている**ので、先へ進まないこと。

- [ ] **Step 5: 走査が効いていることを確認する（故意に壊す）**

`ELEC_REF` を一時的に `re.compile(r"XXXX")` にして走らせる。

```bash
.venv/bin/pytest tools/test_pcb.py -k fit_inside_their_band -q
```

期待: `電子部品を 0 個しか見ていない。走査が壊れている` で FAIL。
**確認したら元に戻す。**（検査対象が空のときに緑になるのを防げていることの確認）

- [ ] **Step 6: コミット**

```bash
git add tools/bands.py tools/gen_pcb.py tools/test_pcb.py
git commit -m "電子部品が帯からはみ出していることを機械で検出する

U1（SOIC-16・コートヤード 10.49mm）が帯 9.25mm に入っていないこと、
J_DB（FFC）も 0.275mm はみ出していることを、検査が言うようにした。
J_DB のはみ出しはこれまで記録に無かった。

帯の定義を bands.py に切り出し、生成側と検査側で共有する。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: 部品をコートヤード基準で置き、U1 を TSSOP-16 にする

**なぜこの順か:** Task 1 の検査を緑にする。**`dy` を手で足すのではなく、置き方そのものを直す。**`J_DB` のはみ出しは原点とコートヤード中心のずれが原因で、`U1` の 10.49mm とは別の問題。両方まとめて消す。

**Files:**
- Modify: `tools/gen_pcb.py`（`ELEC_FP` 341 行付近 / `PLACE` 356–387 / `_place_electronics` 390–422）

**Interfaces:**
- Consumes: `bands.BAND_Y`, `bands.BAND_H`（Task 1）
- Produces: なし（`PLACE` の 3 要素タプルが 2 要素になる）

- [ ] **Step 1: フットプリントを TSSOP-16 に変える**

`ELEC_FP` の 1 行。

```python
    # SOIC-16 はコートヤード 10.49mm で、帯 9.25mm に**入らない**。
    # 位置の微調整で逃がそうとしていたが、どちら側にはみ出すかを
    # 選んでいるだけだった。TSSOP-16 は 5.59mm で 3.66mm 余る。
    "74HC595": ("Package_SO", "TSSOP-16_4.4x5mm_P0.65mm"),
```

- [ ] **Step 2: `PLACE` から `dy`（3 番目の要素）を消す**

`"U1": (0, 13.0, -1.8)` → `"U1": (0, 13.0)`。左の `U1`、右の `U1` と `U2` の 3 箇所。

`PLACE` の上のコメントにある「SOIC-16 は縦 10.4mm あり…位置で逃がす」という説明も消す（もう嘘になる）。

- [ ] **Step 3: `_place_electronics` をコートヤード基準にする**

`fp.Flip(...)` の直後に、コートヤードの中心が帯の中心へ来るよう y を補正する処理を足す。**`dy` の受け取りは消す。**

```python
        band, x = spec[0], spec[1]
        kind, pins = decl[ref]
        lib, name = ELEC_FP[kind]
        n = 2 if kind == "battery_holder" else 1
        for k in range(n):
            fp = _load(KICAD_FP / f"{lib}.pretty", name)
            fp.SetPosition(to_kicad(x + k * 4.0, BAND_Y[band]))
            fp.SetReference(ref if n == 1 else f"{ref}_{'+-'[k]}")
            fp.SetValue(kind)
            board.Add(fp)
            fp.Flip(fp.GetPosition(), False)
            # **原点ではなくコートヤードを帯の中心に合わせる。**
            #
            # フットプリントのコートヤードは原点に対して対称とは限らない
            # （FFC コネクタは 0.95mm ずれていて、帯から 0.275mm はみ出していた）。
            # 原点を中心に置くと、部品ごとに違う量だけずれる。
            # ここで揃えておけば、部品ごとの手当て（dy）が要らなくなる。
            _center_courtyard_in_band(fp, band)
```

同じファイルに補助関数を足す（`_place_electronics` の直前）。

```python
def _center_courtyard_in_band(fp, band):
    """コートヤードの中心が帯の中心へ来るよう、フットプリントを縦にずらす。"""
    for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
        shape = fp.GetCourtyard(layer)
        if not shape.IsEmpty():
            break
    else:
        raise RuntimeError(f"{fp.GetReference()}: コートヤードが無い")
    bb = shape.BBox()
    mid = (bb.GetTop() + bb.GetBottom()) / 2
    want = pcbnew.FromMM(ORIGIN[1] - BAND_Y[band])
    pos = fp.GetPosition()
    fp.SetPosition(pcbnew.VECTOR2I(pos.x, int(pos.y + want - mid)))
```

- [ ] **Step 4: 基板を作り直して検査が緑になることを確認する**

```bash
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9
"$KPY" tools/gen_pcb.py
.venv/bin/pytest tools/test_pcb.py -k fit_inside_their_band -q
```

期待: **両方 PASS。**

- [ ] **Step 5: DRC を測って記録する（単独の効果を残す）**

```bash
.venv/bin/python3 tools/drc.py
```

期待: 違反が左 25 / 右 29 より減る。**減らなくても止まらない。**この変更の目的は「帯に収める」ことで、DRC の件数は Freerouting 導入後に 0 にする。実測値を次のステップのコミットメッセージに書く。

- [ ] **Step 6: 全検査を走らせる**

```bash
.venv/bin/pytest tools -q
```

期待: 全件通過（`WIP_BOARDS` により DRC の検査は skip されたまま）。

- [ ] **Step 7: コミット**

Step 5 で測った実際の数値を `<左>` / `<右>` に入れる。**推測値を書かない。**

```bash
git add tools/gen_pcb.py pcb/
git commit -m "電子部品をコートヤード基準で帯に収め、595 を TSSOP-16 にした

SOIC-16 はコートヤード 10.49mm で帯 9.25mm に入らない。位置の微調整
（PLACE の -1.8）は、どちら側にはみ出すかを選んでいただけだった。
TSSOP-16 は 5.59mm で収まる。

置き方も直した。原点ではなくコートヤードの中心を帯の中心に合わせる。
FFC コネクタは原点が 0.95mm ずれていて帯から出ていたが、これで
部品ごとの dy を持たずに全部まとめて収まる。

違反 左 25→<左> / 右 29→<右>。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: ネットクラスを明示する

**なぜ必要か:** `_apply_jlcpcb_rules` は**最小値**（`min_track_width` ほか）しか設定していない。実際に配線に使われるネットクラスの線幅・クリアランス・ビア径は設定しておらず、`.kicad_pro` に入っている 0.2 / 0.2 / 0.6 / 0.3 は **KiCad の既定値**で、`TRACK_W` と偶然一致していただけ。手書きルータは `TRACK_W` を直接読んでいたので実害が無かったが、**Freerouting はネットクラスしか見ない。**

**Files:**
- Modify: `tools/gen_pcb.py`（`_apply_jlcpcb_rules` 311–323）
- Test: `tools/test_pcb.py`（`test_the_board_declares_the_manufacturer_rules` の隣に追加）

**Interfaces:**
- Consumes: `JLC` 辞書、`TRACK_W` / `VIA_D` / `VIA_DRILL`（`gen_pcb.py` 内）
- Produces: `.kicad_pro` の `net_settings.classes[0]` に意図した値

- [ ] **Step 1: 検査を書く**

`tools/test_pcb.py` に追加する。

```python
@pytest.mark.parametrize("half", NAMES)
def test_the_board_declares_the_netclass_used_for_routing(half):
    """配線に使われるネットクラスが、意図した値で書かれていること。

    **最小値（min_track_width ほか）とは別物。** 最小値は「これを下回るな」
    であって、実際に何 mm で引くかはネットクラスが決める。

    以前ここは設定されておらず、KiCad の既定値が入っていた。たまたま
    意図と同じ 0.2mm だったので誰も気づかなかった。手書きルータは
    TRACK_W を直接読んでいたが、**自動配線器はネットクラスしか見ない。**
    既定値が変われば、黙って別の線幅で配線される。
    """
    import json
    pro = json.loads((PCB / f"hhkb_split_{half}.kicad_pro").read_text())
    cls = pro["net_settings"]["classes"][0]
    assert cls["name"] == "Default"
    for key, mm in (("track_width", 0.2), ("clearance", 0.2),
                    ("via_diameter", 0.6), ("via_drill", 0.3)):
        assert cls[key] == pytest.approx(mm, abs=1e-6), \
            f"{half}: ネットクラスの {key} が {cls[key]}（期待 {mm}）"
```

- [ ] **Step 2: 走らせる（この時点では通ってしまう）**

```bash
.venv/bin/pytest tools/test_pcb.py -k netclass_used_for_routing -q
```

期待: **PASS。**KiCad の既定値が偶然同じ値だからで、これは正常。
**この検査は「値が正しいこと」を守るもので、「コードが設定していること」は守らない。**次のステップでコードを入れ、Step 5 でコードが値を支配していることを確かめる。

- [ ] **Step 3: `_apply_jlcpcb_rules` にネットクラスの設定を足す**

`return board` の直前に入れる。

```python
    # **ネットクラスを明示する。**
    #
    # 上の m_* は「これを下回るな」という最小値であって、実際に何 mm で
    # 引くかを決めるのはネットクラス。ここを設定していなかったので、
    # KiCad の既定値（偶然 TRACK_W と同じ 0.2mm）で配線されていた。
    #
    # 自動配線器はネットクラスしか見ないので、既定値頼みにはできない。
    nc = d.m_NetSettings.GetDefaultNetclass()
    nc.SetTrackWidth(mm(TRACK_W))
    nc.SetClearance(mm(TRACK_W))       # 0.2mm。線幅と同じ
    nc.SetViaDiameter(mm(VIA_D))
    nc.SetViaDrill(mm(VIA_DRILL))
```

この API と、値が `.kicad_pro` の `net_settings.classes[0]` に落ちることは
KiCad 10.0.5 で実測確認済み。**推測ではない**ので、そのまま書いてよい。

（同じ確認で、設定前の既定値が `200000 200000 600000 300000`
＝ 0.2 / 0.2 / 0.6 / 0.3mm であることも確かめた。これがこの Task の前提。）

- [ ] **Step 4: 基板を作り直して検査が通ることを確認する**

```bash
"$KPY" tools/gen_pcb.py
.venv/bin/pytest tools/test_pcb.py -k netclass_used_for_routing -q
```

期待: PASS。

- [ ] **Step 5: コードが値を支配していることを確認する（故意に壊す）**

`nc.SetTrackWidth(mm(TRACK_W))` を `nc.SetTrackWidth(mm(0.25))` に一時変更し、基板を作り直して検査を走らせる。

```bash
"$KPY" tools/gen_pcb.py
.venv/bin/pytest tools/test_pcb.py -k netclass_used_for_routing -q
```

期待: `ネットクラスの track_width が 0.25（期待 0.2）` で **FAIL**。
これで「既定値ではなくコードが決めている」ことが確かめられる。
**確認したら元に戻し、基板を作り直す。**

- [ ] **Step 6: 全検査 → コミット**

```bash
"$KPY" tools/gen_pcb.py
.venv/bin/python3 tools/drc.py
.venv/bin/pytest tools -q
git add tools/gen_pcb.py tools/test_pcb.py pcb/
git commit -m "配線に使うネットクラスを明示する

_apply_jlcpcb_rules は最小値しか設定しておらず、実際に配線に使われる
ネットクラスは KiCad の既定値だった。たまたま TRACK_W と同じ 0.2mm
だったので気づかれていなかった。

手書きルータは TRACK_W を直接読んでいたので実害が無かったが、
自動配線器はネットクラスしか見ない。既定値頼みは残せない。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `autoroute.py` を作り、未配線の基板で通す

**なぜ手書きルータを消さないか:** 先に消すと、Freerouting が期待どおり動かなかったときに戻る先が無くなる。**この Task が終わるまで、手書きルータは既定のまま残す。**

**Files:**
- Create: `tools/autoroute.py`
- Modify: `tools/gen_pcb.py`（`build()` に `route=True` 引数、`main()` に `--no-route` オプション）

**Interfaces:**
- Consumes: `gen_pcb.build(half, keys, route=False)`
- Produces: `autoroute.run(half) -> dict`。キーは `board` / `unrouted` / `unrouted_sha256` / `freerouting` / `passes` の 5 つ。**DRC の件数は含まない**（それは `drc.py` の仕事）。同じ内容を `pcb/route_{half}.json` に書く

**`.gitignore` について:** `pcb/unrouted/*.kicad_pcb` は既存の除外規則
（`*.kicad_prl` / `*.kicad_pcb-bak` / `*-backups/` ほか）に**該当しない**ので、
変更は要らない。Step 2 で `git status` に出ることを確認する。

- [ ] **Step 1: `gen_pcb.py` に未配線で出す道を足す**

`build()` の signature を `def build(half, keys, route=True):` にし、配線の呼び出しを条件にする。

```python
    if route:
        _route(board, positions, rc)
    _place_electronics(board, half, net)
    if route:
        _route_electronics(board, half, net)
```

保存先も分ける。

```python
    OUT.mkdir(exist_ok=True)
    if route:
        path = OUT / f"hhkb_split_{half}.kicad_pcb"
    else:
        (OUT / "unrouted").mkdir(exist_ok=True)
        path = OUT / "unrouted" / f"hhkb_split_{half}.kicad_pcb"
    board.Save(str(path))
```

`main()` に切り替えを足す。

```python
def main():
    route = "--no-route" not in sys.argv
    keys_l, keys_r = split_halves(load_layout(str(ROOT / "layout/hhkb_split.json")))
    for half, keys in (("left", keys_l), ("right", keys_r)):
        path, (w, h), (n_sw, n_stab, n_hole, rows, cols, n_net) = build(half, keys, route)
        ...
```

- [ ] **Step 2: 未配線の基板を出して、本当に配線が無いことを確かめる**

```bash
"$KPY" tools/gen_pcb.py --no-route
grep -c "(segment" pcb/unrouted/hhkb_split_left.kicad_pcb
grep -c "(via" pcb/unrouted/hhkb_split_left.kicad_pcb
```

期待: **両方 0。**（`grep -c` は一致が無いと 0 を表示して終了コード 1 を返す。数字が 0 であればよい）

追跡対象になることも確認する。

```bash
git status --short pcb/unrouted/
```

期待: `?? pcb/unrouted/` が出る（`.gitignore` に食われていない）。

- [ ] **Step 3: `tools/autoroute.py` を書く**

```python
"""未配線の基板を Freerouting に通して配線する。

**手書きのルータをやめた理由**は
docs/superpowers/specs/2026-08-08-pcb-autoroute-design.md にある。
要点は、衝突判定を持たないルータは任意のネット対を短絡させ、
それは経路の調整では 0 にならないということ。

    "$KPY" tools/gen_pcb.py --no-route   # 未配線の基板を出す
    "$KPY" tools/autoroute.py            # 配線する
    .venv/bin/python3 tools/drc.py       # 確かめる

DSN が 4 層・クリアランス規則・NPTH の keepout・GND ベタ（面として）を
運ぶことは実測で確認済み。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "pcb"
UNROUTED = PCB / "unrouted"
HALVES = ("left", "right")
PASSES = 100

JAR = Path(os.environ.get(
    "FREEROUTING_JAR",
    Path.home() / ".local/share/freerouting/freerouting-2.3.0.jar"))


def _java():
    """java の実行ファイル。Homebrew の openjdk は PATH に無いことがある。"""
    for cand in (shutil.which("java"),
                 "/opt/homebrew/opt/openjdk/bin/java",
                 "/usr/local/opt/openjdk/bin/java"):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit(
        "java が見つからない。brew install openjdk を実行すること")


def _check_jar():
    if not JAR.exists():
        raise SystemExit(
            f"Freerouting が見つからない: {JAR}\n"
            "入手:\n"
            "  mkdir -p ~/.local/share/freerouting\n"
            "  curl -L -o ~/.local/share/freerouting/freerouting-2.3.0.jar \\\n"
            "    https://github.com/freerouting/freerouting/releases/download/"
            "v2.3.0/freerouting-2.3.0.jar\n"
            "別の場所に置くなら FREEROUTING_JAR で指定する")


def run(half):
    """未配線の基板を配線し、記録を残して返す。"""
    _check_jar()
    src = UNROUTED / f"hhkb_split_{half}.kicad_pcb"
    if not src.exists():
        raise SystemExit(
            f"未配線の基板が無い: {src}\n"
            'KiCad の Python で "tools/gen_pcb.py --no-route" を実行すること')

    board = pcbnew.LoadBoard(str(src))
    dsn = PCB / f"_{half}.dsn"
    ses = PCB / f"_{half}.ses"
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise SystemExit(f"{half}: DSN の書き出しに失敗した")

    subprocess.run(
        [_java(), "-jar", str(JAR), "-de", str(dsn), "-do", str(ses),
         "-mp", str(PASSES)],
        check=True)
    if not ses.exists():
        raise SystemExit(f"{half}: Freerouting が SES を出さなかった")

    if not pcbnew.ImportSpecctraSES(board, str(ses)):
        raise SystemExit(f"{half}: SES の取り込みに失敗した")

    # **ゾーンを塗り直す。**
    #
    # 「ゾーンを足した」と「塗られた」は別。この案件では 4 層化のときと
    # V3V3 の島のときの 2 回、ここで嵌まっている。SES の取り込みで
    # ビアが増えているので、塗り直さないと GND ベタが古いままになる。
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    out = PCB / f"hhkb_split_{half}.kicad_pcb"
    board.Save(str(out))
    dsn.unlink()
    ses.unlink()

    # **どの未配線基板から作られたかを残す。**
    # これが無いと「配置を変えたのに配線し直していない」が検出できない。
    rec = {
        "board": out.name,
        "unrouted": src.name,
        "unrouted_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "freerouting": JAR.name,
        "passes": PASSES,
    }
    (PCB / f"route_{half}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return rec


def main():
    for half in HALVES:
        rec = run(half)
        print(f"OK {half:5s} {rec['unrouted']} → {rec['board']}"
              f"  ({rec['freerouting']}, {rec['passes']} パス)")
    print("\n配線した。次: .venv/bin/python3 tools/drc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 走らせる**

```bash
export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"
"$KPY" tools/autoroute.py
```

Freerouting は数分かかる。**途中の経過を読むこと。**未配線が残る場合は最後に報告される。

- [ ] **Step 5: DRC で結果を測る**

```bash
.venv/bin/python3 tools/drc.py
```

期待: 左・右ともに**未配線 0**。違反は 0 が目標。

**0 にならない場合の判断**（設計書の「失敗したときの判断」に従う。なし崩しで手書きへ戻さない）:

| 症状 | 手 |
|---|---|
| 未配線が残る | `PASSES` を上げる。`-us global` を `subprocess` の引数に足して試す |
| 違反が出る | 中身を見る。Freerouting は自分のクリアランス規則の中で解くので、出るとすれば **DSN に渡っていない規則**（アニュラリング・外形までの距離）。**規則を渡す側を直す** |
| どちらも解決しない | 実測値を設計書に追記して報告し、判断を仰ぐ。**勝手に手書きルータへ戻さない** |

- [ ] **Step 6: コミット**

実測値を `<左>` / `<右>` に入れる。

```bash
git add tools/autoroute.py tools/gen_pcb.py pcb/
git commit -m "Freerouting で配線する経路を作った（手書きルータはまだ既定）

gen_pcb.py --no-route が未配線の基板を pcb/unrouted/ に出し、
autoroute.py が DSN → Freerouting → SES → ゾーン塗り直し で配線する。

違反 <左> / <右>、未配線 0。

SES 取り込みのあとゾーンを塗り直している。この案件では『足した』と
『塗られた』を取り違える罠に 2 回嵌まっている。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: 手書きルータを削除して切り替える

**前提: Task 4 で未配線 0 が出ていること。**出ていなければこの Task に入らない。

**Files:**
- Modify: `tools/gen_pcb.py`（約 470 行を削除）
- Test: `tools/test_pcb.py`（陳腐化の検査を追加）

**Interfaces:**
- Consumes: `autoroute.run`（Task 4）
- Produces: `gen_pcb.build(half, keys)` は常に未配線を `pcb/unrouted/` へ出す

- [ ] **Step 1: 陳腐化の検査を書く**

`tools/test_pcb.py` に追加する。

```python
@pytest.mark.parametrize("half", NAMES)
def test_the_routing_was_made_from_the_current_placement(half):
    """配線が、いまの未配線基板から作られたものであること。

    **配置を変えたのに配線し直していない状態を検出する。**
    drc.py が「基板を変えたのに DRC をかけ直していない」を見るのと
    同じ型を、一段手前に置いたもの。

    これが無いと、部品を動かしたあと古い配線のまま発注しかねない。
    """
    import hashlib
    import json
    rec_path = PCB / f"route_{half}.json"
    assert rec_path.exists(), \
        f"{half}: 配線の記録が無い。tools/autoroute.py を実行すること"
    rec = json.loads(rec_path.read_text())
    src = PCB / "unrouted" / f"hhkb_split_{half}.kicad_pcb"
    assert src.exists(), f"{half}: 未配線の基板が無い: {src}"
    now = hashlib.sha256(src.read_bytes()).hexdigest()
    assert rec["unrouted_sha256"] == now, (
        f"{half}: 配置が変わったのに配線し直していない。"
        'KiCad の Python で "tools/gen_pcb.py --no-route" のあと '
        '"tools/autoroute.py" を実行すること')
```

- [ ] **Step 2: 通ることを確認する**

```bash
.venv/bin/pytest tools/test_pcb.py -k routing_was_made_from -q
```

期待: PASS。

- [ ] **Step 3: 効いていることを確認する（故意に壊す）**

```bash
printf '\n' >> pcb/unrouted/hhkb_split_left.kicad_pcb
.venv/bin/pytest tools/test_pcb.py -k routing_was_made_from -q
```

期待: `left: 配置が変わったのに配線し直していない` で **FAIL**。

戻す:

```bash
git checkout pcb/unrouted/hhkb_split_left.kicad_pcb
```

- [ ] **Step 4: 手書きルータを削除する**

`tools/gen_pcb.py` から以下を消す。

| 対象 | 現在の行 |
|---|---|
| `TRACK_W` 以外の配線用定数（`COL_VIA_DX` / `LANE_CENTER` / `LANE_SPACING`） | 131–151 |
| `_track` / `_via` / `_pad` | 154–175 |
| `_route` | 178–284 |
| `_fcu_verticals` | 441–455 |
| `_clear_x` | 458–483 |
| `_route_electronics` | 486–585 |
| `_nearest_via` | 587–597 |
| `_link` | 599–628 |

**残すもの:** `TRACK_W` / `VIA_D` / `VIA_DRILL`（Task 3 でネットクラスに使う）、`_pour`、`_npth_holes`（フットプリントの走査に使うなら残す。使わなくなったなら消す）。

`build()` から `route` 引数と分岐を消し、常に `pcb/unrouted/` へ出すようにする。`main()` から `--no-route` も消す（既定になったので不要）。

配線の層構成を説明しているコメント（741–747 行付近）は、**自動配線に委ねた旨に書き換える**。嘘のコメントを残さない。

- [ ] **Step 5: 使われなくなったものが残っていないか確かめる**

```bash
cd /Users/m/Library/CloudStorage/OneDrive-個人用/workspace/2608042258_HHKB_devided
grep -n "_track(\|_via(\|_pad(\|_link(\|_clear_x\|_fcu_verticals\|_nearest_via\|LANE_\|COL_VIA_DX" tools/gen_pcb.py
```

期待: **何も出ない**（`gen_daughterboard.py` は対象外なので触らない）。

- [ ] **Step 6: 一通り走らせる**

```bash
"$KPY" tools/gen_pcb.py
export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"
"$KPY" tools/autoroute.py
.venv/bin/python3 tools/drc.py
.venv/bin/pytest tools -q
```

期待: 未配線 0、全検査通過。

- [ ] **Step 7: コミット**

```bash
git add tools/gen_pcb.py tools/test_pcb.py pcb/
git commit -m "手書きルータを削除し、配線を Freerouting に一本化した

gen_pcb.py は配置・ネット・ゾーン・設計規則だけを持つ。約 470 行が
消えた。残った部分（interface.py に縛られた配置、matrix.py 経由で
ファームと同期したネット、JLCPCB 規則、シルク線幅の担保）が、この
ファイルの本来の仕事。

配線の記録に未配線基板の sha256 を埋め、『配置を変えたのに配線し
直していない』を検査が検出するようにした。故意に壊して落ちることを
確認済み。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: DRC 0 を確定し、WIP_BOARDS を空にして文書を更新する

**Files:**
- Modify: `tools/test_pcb.py`（`WIP_BOARDS`）
- Modify: `docs/hardware/pcb-routing-handover.md`
- Modify: `docs/hardware/open-gaps.md`（#16）
- Modify: `CLAUDE.md`（よく使うコマンドに `autoroute.py` を足す）

- [ ] **Step 1: DRC が 0 であることを確認する**

```bash
.venv/bin/python3 tools/drc.py
```

期待: 3 基板すべて `OK ... 違反 0 / 未配線 0`。

**0 でなければここで止まり、残りの違反の内訳を報告する。**`WIP_BOARDS` を空にしてはいけない（偽の緑になる）。

- [ ] **Step 2: `WIP_BOARDS` を空にする**

```python
# 未完の基板。ここに名前がある間は発注できない。
# **空 = 3 基板すべて DRC 違反 0・未配線 0。**
WIP_BOARDS = set()
```

- [ ] **Step 3: 全検査を走らせる**

```bash
.venv/bin/pytest tools -q
```

期待: 全件通過。**`test_the_board_has_no_drc_violations` が skip ではなく PASS になっていること**を確認する（`-v` で見る）。

```bash
.venv/bin/pytest tools/test_pcb.py -k no_drc_violations -v
```

- [ ] **Step 4: `CLAUDE.md` のコマンド一覧を直す**

「基板の生成は KiCad の Python で」の節に足す。

```
"$KPY" tools/gen_pcb.py          # 未配線の基板（pcb/unrouted/）
"$KPY" tools/autoroute.py        # Freerouting で配線して pcb/ に出す
"$KPY" tools/gen_daughterboard.py
```

- [ ] **Step 5: 引き継ぎ書を書き直す**

`docs/hardware/pcb-routing-handover.md` を、いまの状態に合わせて全面的に書き直す。**残すべきもの:**

- 「やってはいけないこと」の 3 項目（接頭辞での走査など）は**そのまま残す**。まだ有効な教訓
- 手書きルータをやめた理由と、そのときの実測値。**「試して失敗した手」として残す**（同じことを繰り返させないため）
- 「効いた手」の表のうち、コネクタのピン順と部品の並びを揃える件は残す（配置の話なので今も有効）

**消すもの:** レーン・通路・`_clear_x` の調整に関する記述（コードごと無くなった）、V3V3 をベタで配る案（自動配線が引くので不要）。

- [ ] **Step 6: `open-gaps.md` の #16 を閉じる**

該当の節に解決済みの印と日付を入れる。この案件の作法（`test_invariants.py` が表と設計値のずれを検出する）に従い、**表から行を消すのか印を付けるのかは、既存の #3 / #4 の書き方に合わせる**（`✅ 2026-08-07 解決` の形）。

- [ ] **Step 7: 最終確認**

```bash
.venv/bin/pytest tools -q
.venv/bin/python3 tools/gen_assembly.py
```

期待: 全検査通過、組み立て干渉 0。

- [ ] **Step 8: コミット**

```bash
git add tools/test_pcb.py docs/ CLAUDE.md
git commit -m "本体基板の配線が通った（3 基板すべて DRC 違反 0・未配線 0）

WIP_BOARDS が空になった。open-gaps #16 を閉じた。

引き継ぎ書を書き直し、手書きルータをやめた経緯を『試して失敗した手』
として残した。接頭辞での走査に関する教訓は今も有効なので残してある。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## この計画で守られていること

- `tools/interface.py` に触れていない（凍結境界）
- `tools/gen_daughterboard.py` に触れていない（すでに違反 0）
- 新しい検査 3 つ（帯・ネットクラス・陳腐化）は、いずれも**故意に壊して落ちることを確認する手順つき**
- Freerouting が期待どおり動かなかった場合に、**なし崩しで手書きへ戻さないための判断基準**が Task 4 Step 5 にある
- 各 Task の終わりでリポジトリが壊れていない（Task 4 まで手書きルータが既定のまま残る）
