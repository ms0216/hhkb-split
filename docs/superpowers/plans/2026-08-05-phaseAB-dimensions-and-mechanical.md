# フェーズ A・B: 寸法確定と機構設計 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HHKB の寸法を実機採寸に頼らず確定させ、そこからケースとプレートを CAD で設計し、**3Dプリントした実物を HHKB と並べて比較できる状態**まで到達する。基板は1枚も作らない。

**Architecture:** 配列を KLE JSON 1ファイルに集約し、それを唯一の入力としてプレート・ケース・（後のフェーズで）PCB を生成する。CAD は build123d（Python）で記述し、生成物を PNG レンダリング・干渉チェック・寸法アサーションの3方法で自己検証してから印刷に回す。

**Tech Stack:** Python 3.13 / build123d (OCCT) / trimesh / Pillow・NumPy / KiCad 9 + kicad-cli / ZMK

## Global Constraints

- 対象仕様書: [docs/superpowers/specs/2026-08-04-hhkb-split-keyboard-design.md](../specs/2026-08-04-hhkb-split-keyboard-design.md)
- キーピッチは 1u = **19.05mm**。すべての座標はこれを基準にする。
- ベース機の公称寸法（訂正不可の基準値）: **幅 294mm / 奥行 108mm / 高さ 手前 20mm・奥 32mm（フレームまで）**。チルトスタンドは **0° / 3° / 6°** の3段階。
- MX 軸のプレート開口は **14.0mm 角**。プレート厚は **1.5mm**（FR4 1.6mm でも成立する寸法にする）。
- 単3電池の寸法: **直径 14.5mm × 長さ 50.5mm**。2本並列で 29.0 × 50.5mm の空間を要する。
- **ユーザーに測定を依頼しない。** 検証はすべて「1:1 印刷物を実機に重ねる」「印刷した部品を実機と並べる」形で行う。定規・ノギスを使わせない。
- 生成物（STL / STEP / PDF / ガーバー）は git にコミットしない。生成スクリプトのみをコミットし、`make` 相当のコマンドでいつでも再生成できる状態を保つ。
- **3Dプリンター: Creality K1 Max / PLA**。この制約に合わせて設計する。
  - 造形サイズ 300 × 300 × 300mm。左右どちらの部品も分割せず 1 回で刷れる。
  - ノズル 0.4mm。**肉厚は 0.4mm の整数倍**にする（壁 2.4mm = 6 周）。中途半端な厚みはスライサーが埋められず空隙になる。
  - 積層 0.2mm を標準とする。Z 方向の寸法は 0.2mm の倍数に寄せる。
  - PLA の耐熱は約 60℃。屋内使用なので問題ないが、**直射日光の当たる車内などに放置しない**前提とする。
  - 穴は収縮で 0.1〜0.2mm 小さく仕上がる。嵌合部の穴は設計値に **+0.2mm のクリアランス**を見込む。
  - オーバーハングは 45° まで。電池蓋のスライドレールは、サポート無しで刷れる形状にする。

---

## File Structure

```
tools/
  requirements.txt              Python 依存（build123d, trimesh, pillow, numpy）
  measure_photo.py              フェーズA: 公式写真からキー位置を計測する
  layout.py                     KLE JSON を読み、キー座標(mm)のリストに変換する共通モジュール
  gen_template.py               フェーズA: 1:1 照合用 PDF を出力する
  gen_plate.py                  フェーズB: スイッチプレートを生成する
  gen_case.py                   フェーズB: ボトムケースを生成する
  verify.py                     フェーズB: レンダリング・干渉・寸法アサーションの自己検証
layout/
  hhkb_original.json            KLE 形式。ベース機の配列（計測で確定させる）
  hhkb_split.json               KLE 形式。分割版の配列（設計対象）
docs/hardware/
  dimensions.md                 フェーズA の成果。確定した寸法とその根拠
  photo-measurement.md          写真計測の手法と誤差評価
  phaseB-results.md             フェーズB の判定と申し送り
build/                          生成物置き場（.gitignore 済み）
```

`tools/layout.py` が中心。KLE JSON を「キーごとの中心座標(mm)・幅・高さ・回転」に変換する 1 つの関数を提供し、テンプレート・プレート・ケース・PCB がすべてこれを呼ぶ。配列を変えたら全部が追従する。

---

## フェーズ A: 寸法の確定と配列のデータ化

### Task A1: ツール導入と自己検証環境の確立

以降の全タスクは、私（エージェント）が結果を確認できることに依存する。まずその足場を作る。

**Files:**
- Create: `tools/requirements.txt`
- Create: `tools/smoke_test.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `build123d` / `trimesh` / `kicad-cli` が動く環境と、それを確認する `tools/smoke_test.py`。以降のタスクはこれが通ることを前提にする。

- [ ] **Step 1: Python 依存を定義する**

`tools/requirements.txt`:

```
build123d>=0.9
trimesh>=4.0
numpy>=2.0
pillow>=11.0
matplotlib>=3.9
```

`matplotlib` は STL をオフスクリーンで PNG にするために使う。GPU も表示環境も不要。

- [ ] **Step 2: 仮想環境を作って導入する**

```bash
cd "/Users/m/Library/CloudStorage/OneDrive-個人用/workspace/2608042258_HHKB_devided"
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt
```

`build123d` は OCCT のバイナリホイール（`cadquery-ocp`）を引くため 300MB 程度のダウンロードになる。

- [ ] **Step 3: KiCad を導入する**

```bash
brew install --cask kicad
ls /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
```

フェーズ B では使わないが、フェーズ D で必要になるうえ、導入に時間がかかるためここで済ませる。`kicad-cli` はパスが通らないので、フルパスか alias で使う。

- [ ] **Step 4: スモークテストを書く**

`tools/smoke_test.py`:

```python
"""導入したツールが動くことを確認し、自己検証の3手法が機能することを示す。"""
import sys
from pathlib import Path

import numpy as np
import trimesh
from build123d import Box, Cylinder, Mode, BuildPart, Location, export_stl

BUILD = Path(__file__).resolve().parent.parent / "build"
BUILD.mkdir(exist_ok=True)


def make_test_part():
    """20mm 立方体に直径 10mm の穴を開けた形状。"""
    with BuildPart() as part:
        Box(20, 20, 20)
        with Locations((0, 0, 0)):
            Cylinder(radius=5, height=30, mode=Mode.SUBTRACT)
    return part.part


def main():
    from build123d import Locations  # noqa: F401  (make_test_part で使う)

    part = make_test_part()

    # 検証1: 寸法アサーション
    bb = part.bounding_box()
    assert abs(bb.size.X - 20) < 1e-6, f"X が 20mm でない: {bb.size.X}"
    assert abs(bb.size.Z - 20) < 1e-6, f"Z が 20mm でない: {bb.size.Z}"
    expected_volume = 20**3 - np.pi * 5**2 * 20
    assert abs(part.volume - expected_volume) / expected_volume < 1e-3, (
        f"体積が想定と違う: {part.volume} vs {expected_volume}"
    )
    print(f"OK 寸法アサーション: bbox={bb.size}, volume={part.volume:.1f}")

    # 検証2: STL を出して mesh として読み直せる（水密であること）
    stl = BUILD / "smoke.stl"
    export_stl(part, str(stl))
    mesh = trimesh.load(str(stl))
    assert mesh.is_watertight, "STL が水密でない（印刷できない形状）"
    print(f"OK STL 出力: {stl}, watertight={mesh.is_watertight}")

    # 検証3: PNG レンダリング（私が目視で確認するため）
    render_png(mesh, BUILD / "smoke.png")
    print(f"OK レンダリング: {BUILD / 'smoke.png'}")


def render_png(mesh, out_path, elev=25, azim=-60):
    """matplotlib で三角形メッシュをオフスクリーン描画する。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    fig = plt.figure(figsize=(8, 6), dpi=150)
    ax = fig.add_subplot(111, projection="3d")
    ax.add_collection3d(
        Poly3DCollection(
            mesh.triangles, facecolor="#b0c4de", edgecolor="none", alpha=1.0
        )
    )
    b = mesh.bounds
    ax.set_xlim(b[0][0], b[1][0])
    ax.set_ylim(b[0][1], b[1][1])
    ax.set_zlim(b[0][2], b[1][2])
    ax.set_box_aspect(b[1] - b[0])
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 実行して 3 手法すべてが動くことを確認する**

```bash
.venv/bin/python tools/smoke_test.py
```

期待: 3 行の `OK` が出て、`build/smoke.png` が生成されること。

**生成された PNG を Read ツールで開いて目視する。** 「20mm の立方体に穴が空いている」ように見えれば、私が自分の CAD 出力を確認できる経路が確立したことになる。見えなければ、この時点でレンダリング方法を作り直す。ここが機能しないまま先へ進まない。

- [ ] **Step 6: 生成物を git 管理外にする**

`.gitignore` に追加:

```
# Python
.venv/

# 生成物（スクリプトから再生成できるため管理しない）
build/
```

- [ ] **Step 7: コミット**

```bash
git add tools .gitignore
git commit -m "feat: CAD ツールと自己検証環境を導入"
```

---

### Task A2: 公式写真からの寸法計測

ベース機で唯一不明な**下段の水平位置**（◇ と Alt の幅、左右の余白）を、公式製品写真から割り出す。

**Files:**
- Create: `tools/measure_photo.py`
- Create: `docs/hardware/photo-measurement.md`
- Create: `build/photos/`（生成物、git 管理外）

**Interfaces:**
- Produces: 下段 5 キーの幅と左右余白（mm）。Task A3 の KLE JSON がこれを使う。
- Produces: `docs/hardware/photo-measurement.md` — 手法と誤差評価。後で寸法を疑ったときの根拠になる。

- [ ] **Step 1: 真上からの製品写真を取得する**

PFU 公式の製品ページから、最も解像度が高く、かつ真上に近い角度の画像を取得する。候補:

- https://www.pfu.ricoh.com/direct/hhkb/detail_pd-kb800wns.html
- https://happyhackingkb.com/jp/products/hybrid_types/

```bash
mkdir -p build/photos
# 画像 URL を特定してから
curl -sSL -o build/photos/hhkb_top.jpg "<画像URL>"
.venv/bin/python -c "
from PIL import Image
im = Image.open('build/photos/hhkb_top.jpg')
print(im.size, im.mode)
"
```

**判定**: 幅 1500px 以上あること。それ未満だと 1px あたり 0.2mm を超え、目標精度 ±0.3mm に届かない。届かない場合は、他の高解像度な出典（レビュー記事の実測写真、販売店の商品画像）を探す。

**取得した画像を Read ツールで開いて目視する。** 真上から撮られているか、遠近で奥の列が小さく写っていないかを確認する。斜めであれば Step 3 の射影補正が必須になる。

- [ ] **Step 2: 計測スクリプトを書く**

`tools/measure_photo.py`:

```python
"""公式製品写真から HHKB のキー位置を計測する。

手法:
  1. 既知の全幅 294mm でピクセル→mm のスケールを較正する
  2. 英数キー列の 19.05mm ピッチで二重に較正し、スケール誤差を検出する
  3. 下段のキー境界を検出し、幅と余白を mm で出力する
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BOARD_WIDTH_MM = 294.0
UNIT_MM = 19.05


def load_gray(path):
    im = Image.open(path).convert("L")
    return np.asarray(im, dtype=np.float32)


def column_profile(gray, y0, y1):
    """指定した行範囲の輝度を縦方向に平均し、横方向のプロファイルを得る。
    キーの隙間は暗く写るため、谷がキー境界になる。"""
    return gray[y0:y1, :].mean(axis=0)


def find_valleys(profile, min_distance):
    """プロファイルの局所最小（キーの隙間）を検出する。"""
    smoothed = np.convolve(profile, np.ones(5) / 5, mode="same")
    valleys = []
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] <= smoothed[i - 1] and smoothed[i] < smoothed[i + 1]:
            if not valleys or i - valleys[-1] >= min_distance:
                valleys.append(i)
    return np.array(valleys)


def calibrate(left_edge_px, right_edge_px):
    """全幅からスケールを決める。"""
    return BOARD_WIDTH_MM / (right_edge_px - left_edge_px)


def verify_scale(alpha_valleys_px, mm_per_px):
    """英数キー列の隣接ピッチが 19.05mm になるかで較正を検証する。"""
    pitches = np.diff(alpha_valleys_px) * mm_per_px
    return pitches.mean(), pitches.std()


def main(path):
    gray = load_gray(path)
    h, w = gray.shape
    print(f"画像サイズ: {w} x {h} px")
    # 以降、実際の画像を見ながら y 範囲と端の px 位置を決める。
    # このスクリプトは対話的に詰めるため、値は実行時に確定させる。


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/photos/hhkb_top.jpg")
```

- [ ] **Step 3: 較正と歪みの検証を行う**

1. 本体の左右端のピクセル位置を検出し、`mm_per_px = 294.0 / (右端 - 左端)` を求める
2. 英数キー列（例: `Q W E R T Y U I O P`）の隣接する隙間の間隔を測り、`verify_scale` で 19.05mm と比較する

**判定基準:**
- 平均ピッチが 19.05mm から **±0.3mm 以内**、かつ標準偏差が **0.2mm 以内** → 較正成功。Step 4 へ
- 上段と下段でピッチが系統的に異なる → 遠近歪みあり。4 隅の座標から射影変換行列を作り、画像を正射投影に補正してから Step 3 をやり直す
- どうしても収束しない → 別の写真を探す。それでも駄目なら Step 6 の代替手段へ

- [ ] **Step 4: 下段の水平位置を計測する**

最下段（スペースバーのある行）の輝度プロファイルからキー境界を検出し、以下を mm で出力する。

| 計測項目 | 記号 |
|---|---|
| 本体左端 → 左◇ の左端 | `gap_left` |
| 左◇ の幅 | `w_diamond_l` |
| 左 Alt の幅 | `w_alt_l` |
| スペースバーの幅 | `w_space` |
| 右 Alt の幅 | `w_alt_r` |
| 右◇ の幅 | `w_diamond_r` |
| 右◇ の右端 → 本体右端 | `gap_right` |

**整合性チェック**: 上記 7 つの合計が 294mm（＝15u）になること。ずれが 1mm を超えたら計測を疑う。

さらに、各幅を 19.05mm で割って u 単位に直し、**0.25u の倍数に丸まるか**を確認する。キーキャップの規格サイズは 0.25u 刻みなので、丸まらなければ計測かキー境界の検出が間違っている。

- [ ] **Step 5: 計測結果と誤差評価を記録する**

`docs/hardware/photo-measurement.md` を作成する。

```markdown
# 写真計測によるベース機の寸法確定

## 出典

- 画像: （URL）
- 解像度: （px）
- 撮影角度の評価: （真上か、補正の要否）

## 較正

| 項目 | 値 |
|---|---|
| 本体左端 / 右端（px） | |
| mm/px | |
| 英数キー列の平均ピッチ | mm（規格 19.05mm との差: mm） |
| 同 標準偏差 | mm |

## 下段の計測結果

| 項目 | px | mm | u 換算 | 丸めた値 |
|---|---|---|---|---|
| gap_left | | | | |
| 左◇ | | | | |
| 左 Alt | | | | |
| スペースバー | | | | |
| 右 Alt | | | | |
| 右◇ | | | | |
| gap_right | | | | |
| **合計** | | | **15.00u** | |

## 誤差評価

推定誤差: ±（）mm。根拠: 1px = （）mm、境界検出のばらつき（）px。

## 結論

（下段の構成を u 単位で確定させた記述）
```

- [ ] **Step 6（Step 3 または 4 が失敗した場合のみ）: 代替手段**

写真計測が目標精度に届かない場合、以下の順で試す。

1. **別の写真**: レビュー記事の実測写真、販売店の商品画像、分解記事の基板写真（基板写真ならキー位置がより明確）
2. **キーキャップの規格から逆算**: HHKB 互換の交換用キーキャップセットを販売している店の商品ページには、各キーのサイズが u 単位で記載されていることがある。これは実測より信頼できる一次情報になりうる
3. **1:1 テンプレートによる二分探索**: 候補となる構成を複数（例: `1.5/1/6/1/1.5` と `1.5/1.5/6/1.5/1.5`）テンプレートに並べて印刷し、実機に重ねてどれが一致するかを見てもらう。**測定ではなく照合**なので、依頼として成立する

- [ ] **Step 7: コミット**

```bash
git add tools/measure_photo.py docs/hardware/photo-measurement.md
git commit -m "feat: 公式写真からベース機の下段寸法を計測"
```

---

### Task A3: 配列の KLE JSON 化

計測結果をもとに、ベース機と分割版の配列を機械可読なデータにする。以降のすべての生成物がこの 2 ファイルから作られる。

**Files:**
- Create: `layout/hhkb_original.json`
- Create: `layout/hhkb_split.json`
- Create: `tools/layout.py`
- Create: `tools/test_layout.py`

**Interfaces:**
- Produces: `tools/layout.py` の `load_layout(path) -> list[Key]`。`Key` は `x_mm`, `y_mm`（中心座標）, `w_u`, `h_u`, `label` を持つ。Task A4・B1・B3、およびフェーズ D の PCB 生成がこれを呼ぶ。
- Produces: `layout/hhkb_split.json` — 61 キーの分割配列。

- [ ] **Step 1: ベース機の KLE JSON を書く**

`layout/hhkb_original.json`。Task A2 で確定した下段の値を使う。KLE 形式は「行の配列」で、`{"w": 1.5}` のようなオブジェクトが次のキーの属性を指定する。

上4段は既知:

```json
[
  ["Esc","1","2","3","4","5","6","7","8","9","0","-","=","\\","`"],
  [{"w":1.5},"Tab","Q","W","E","R","T","Y","U","I","O","P","[","]",{"w":1.5},"Del"],
  [{"w":1.75},"Ctrl","A","S","D","F","G","H","J","K","L",";","'",{"w":2.25},"Enter"],
  [{"w":2.25},"Shift","Z","X","C","V","B","N","M",",",".","/",{"w":1.75},"Shift","Fn"],
  [{"x":<gap_left>,"w":<w_diamond_l>},"◇",{"w":<w_alt_l>},"Alt",{"w":<w_space>},"",{"w":<w_alt_r>},"Alt",{"w":<w_diamond_r>},"◇"]
]
```

最下段の `<...>` を Task A2 の確定値で埋める。

- [ ] **Step 2: 分割版の KLE JSON を書く**

`layout/hhkb_split.json`。左 27 キー・右 34 キーで、スペースは 3u × 2。左右は別々の「島」として、間に十分な間隔（例: 40mm）を空けて配置する。

上4段の分割位置は仕様書 §2 のとおり。行ずれ（各行の開始 x オフセット）はベース機と同一にする。右半分は行ごとに 0 / 0.5u / 0.75u / 1.25u だけ内側に入る。

- [ ] **Step 3: KLE 読み込みモジュールを書く**

`tools/layout.py`:

```python
"""KLE JSON を読み、キーごとの実寸座標(mm)に変換する。

このモジュールが配列の唯一の入口。テンプレート・プレート・ケース・PCB は
すべてここを経由するので、配列を変えたら全部が追従する。
"""
import json
from dataclasses import dataclass
from pathlib import Path

UNIT_MM = 19.05


@dataclass(frozen=True)
class Key:
    x_mm: float       # キー中心の X（右が正、原点は配列の左上）
    y_mm: float       # キー中心の Y（下が正）
    w_u: float        # 幅（u）
    h_u: float        # 高さ（u）
    label: str

    @property
    def w_mm(self) -> float:
        return self.w_u * UNIT_MM

    @property
    def h_mm(self) -> float:
        return self.h_u * UNIT_MM


def load_layout(path) -> list[Key]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    keys: list[Key] = []
    y = 0.0
    for row in raw:
        if not isinstance(row, list):
            continue  # 先頭のメタデータオブジェクトは読み飛ばす
        x = 0.0
        w = h = 1.0
        for item in row:
            if isinstance(item, dict):
                x += float(item.get("x", 0))
                y += float(item.get("y", 0))
                w = float(item.get("w", 1))
                h = float(item.get("h", 1))
                continue
            keys.append(
                Key(
                    x_mm=(x + w / 2) * UNIT_MM,
                    y_mm=(y + h / 2) * UNIT_MM,
                    w_u=w,
                    h_u=h,
                    label=str(item),
                )
            )
            x += w
            w = h = 1.0
        y += 1.0
    return keys


def bounds_mm(keys: list[Key]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) をキーの外形で返す。"""
    xs0 = [k.x_mm - k.w_mm / 2 for k in keys]
    xs1 = [k.x_mm + k.w_mm / 2 for k in keys]
    ys0 = [k.y_mm - k.h_mm / 2 for k in keys]
    ys1 = [k.y_mm + k.h_mm / 2 for k in keys]
    return min(xs0), min(ys0), max(xs1), max(ys1)
```

- [ ] **Step 4: テストを書く**

`tools/test_layout.py`:

```python
"""layout.py が配列を正しく実寸に変換することを、既知の事実で検証する。"""
from layout import UNIT_MM, bounds_mm, load_layout

ORIGINAL = "layout/hhkb_original.json"
SPLIT = "layout/hhkb_split.json"


def test_original_has_60_keys():
    keys = load_layout(ORIGINAL)
    assert len(keys) == 60, f"ベース機は 60 キーのはず: {len(keys)}"


def test_original_width_is_294mm():
    keys = load_layout(ORIGINAL)
    x0, _, x1, _ = bounds_mm(keys)
    width = x1 - x0
    assert abs(width - 294.0) < 1.0, f"全幅が公称 294mm と合わない: {width:.2f}"


def test_original_rows_are_15u():
    """上 4 段はいずれも合計 15u であること。"""
    keys = load_layout(ORIGINAL)
    rows: dict[float, float] = {}
    for k in keys:
        rows[k.y_mm] = rows.get(k.y_mm, 0.0) + k.w_u
    top4 = sorted(rows)[:4]
    for y in top4:
        assert abs(rows[y] - 15.0) < 1e-6, f"y={y} の行が 15u でない: {rows[y]}"


def test_split_has_61_keys():
    keys = load_layout(SPLIT)
    assert len(keys) == 61, f"分割版は 61 キーのはず: {len(keys)}"


def test_split_has_two_3u_spaces():
    keys = load_layout(SPLIT)
    spaces = [k for k in keys if abs(k.w_u - 3.0) < 1e-6]
    assert len(spaces) == 2, f"3u スペースが 2 つあるはず: {len(spaces)}"


def test_split_key_pitch_is_19_05():
    """英数キーの隣接間隔が 19.05mm であること。"""
    keys = load_layout(SPLIT)
    ones = sorted(
        (k for k in keys if abs(k.w_u - 1.0) < 1e-6), key=lambda k: (k.y_mm, k.x_mm)
    )
    same_row = [k for k in ones if abs(k.y_mm - ones[0].y_mm) < 1e-6]
    diffs = [b.x_mm - a.x_mm for a, b in zip(same_row, same_row[1:])]
    for d in diffs:
        if d < UNIT_MM * 1.5:  # 島の切れ目は無視する
            assert abs(d - UNIT_MM) < 1e-6, f"ピッチが 19.05mm でない: {d}"
```

- [ ] **Step 5: テストを走らせて失敗することを確認する**

```bash
.venv/bin/pip install pytest
cd "/Users/m/Library/CloudStorage/OneDrive-個人用/workspace/2608042258_HHKB_devided"
PYTHONPATH=tools .venv/bin/python -m pytest tools/test_layout.py -v
```

期待: JSON がまだ不完全なら失敗する。失敗の内容を見て JSON を直す。

- [ ] **Step 6: テストが全部通るまで JSON を直す**

```bash
PYTHONPATH=tools .venv/bin/python -m pytest tools/test_layout.py -v
```

期待: 6 件すべて PASS。

`test_original_width_is_294mm` が通ることが特に重要で、これは**写真計測で得た下段の値と、公称の全幅 294mm が矛盾しない**ことの確認になる。

- [ ] **Step 7: コミット**

```bash
git add layout tools
git commit -m "feat: 配列を KLE JSON 化し、実寸変換モジュールとテストを追加"
```

---

### Task A4: 1:1 照合テンプレートの出力と検証

確定した寸法が正しいことを、ユーザーに測定させずに確認する。

**Files:**
- Create: `tools/gen_template.py`
- Create: `docs/hardware/dimensions.md`

**Interfaces:**
- Consumes: `tools/layout.py` の `load_layout`。
- Produces: `build/template_original.pdf` — 実機に重ねる 1:1 の図。
- Produces: `docs/hardware/dimensions.md` — 確定した寸法の一覧。フェーズ B の CAD がこれを参照する。

- [ ] **Step 1: テンプレート生成スクリプトを書く**

`tools/gen_template.py`。A4 に収まらない幅（294mm）なので、**A4 横 2 枚に分割し、貼り合わせ用のトンボを入れる**。

```python
"""1:1 の照合用 PDF を出力する。印刷して実機に重ねるためのもの。

- 各キーの外形を実線で描く
- 本体外形を太線で描く
- 100mm の基準スケールを入れる（印刷倍率がずれていないかの確認用）
- A4 横 2 枚に分割し、貼り合わせのトンボを入れる
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout import bounds_mm, load_layout  # noqa: E402

MM = 1 / 25.4  # mm → inch
A4_W, A4_H = 297.0, 210.0  # A4 横
MARGIN = 10.0


def draw(ax, keys, x_offset, board):
    bx0, by0, bx1, by1 = board
    ax.add_patch(
        Rectangle(
            (bx0 - x_offset, by0), bx1 - bx0, by1 - by0,
            fill=False, linewidth=1.2, edgecolor="black",
        )
    )
    for k in keys:
        ax.add_patch(
            Rectangle(
                (k.x_mm - k.w_mm / 2 - x_offset, k.y_mm - k.h_mm / 2),
                k.w_mm, k.h_mm,
                fill=False, linewidth=0.4, edgecolor="black",
            )
        )
    # 基準スケール（100mm）
    y = by1 + 8
    ax.plot([bx0 - x_offset, bx0 - x_offset + 100], [y, y], color="red", linewidth=1.0)
    for t in (0, 100):
        ax.plot([bx0 - x_offset + t] * 2, [y - 2, y + 2], color="red", linewidth=1.0)
    ax.text(bx0 - x_offset + 50, y + 3, "100 mm", ha="center", color="red", fontsize=7)


def main(layout_path, out_path, sheets=2):
    keys = load_layout(layout_path)
    board = bounds_mm(keys)
    bx0, by0, bx1, by1 = board
    width = bx1 - bx0
    per_sheet = width / sheets

    with PdfPages(out_path) as pdf:
        for i in range(sheets):
            fig = plt.figure(figsize=(A4_W * MM, A4_H * MM))
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(0, A4_W)
            ax.set_ylim(A4_H, 0)  # Y を下向きに
            ax.set_aspect("equal")
            ax.set_axis_off()
            draw(ax, keys, x_offset=bx0 + i * per_sheet - MARGIN, board=board)
            ax.text(MARGIN, A4_H - 5, f"sheet {i + 1}/{sheets}  1:1", fontsize=8)
            pdf.savefig(fig)
            plt.close(fig)
    print(f"OK {out_path} ({sheets} 枚, 全幅 {width:.2f}mm)")


if __name__ == "__main__":
    main("layout/hhkb_original.json", "build/template_original.pdf")
```

- [ ] **Step 2: 生成して自己確認する**

```bash
PYTHONPATH=tools .venv/bin/python tools/gen_template.py
```

生成された PDF を PNG に変換して**私が目視する**:

```bash
.venv/bin/pip install pdf2image
brew install poppler
.venv/bin/python -c "
from pdf2image import convert_from_path
for i, p in enumerate(convert_from_path('build/template_original.pdf', dpi=100)):
    p.save(f'build/template_{i}.png')
    print(f'build/template_{i}.png')
"
```

**PNG を Read ツールで開き、HHKB の配列に見えることを確認する。** キーの並びが崩れている、行がずれている、キーが重なっているといった異常があれば、印刷を依頼する前にここで直す。

- [ ] **Step 3: 印刷と照合を依頼する**

ユーザーへの依頼はこの 1 つだけ。

> `build/template_original.pdf` を **A4 横・倍率 100%（「実際のサイズ」「拡大縮小しない」）** で 2 枚印刷し、赤い基準線が定規でちょうど 100mm になっていることを確認してから、2 枚をトンボで貼り合わせて HHKB の上に重ね、真上から写真を撮ってください。

「定規で 100mm を確認」は測定ではなく印刷倍率の確認なので、依頼として成立する。

- [ ] **Step 4: 写真を見て判定する**

送られた写真を Read ツールで開き、以下を確認する。

| 確認項目 | 合格条件 |
|---|---|
| 本体外形 | テンプレートの太線が実機の外形と一致する |
| 上 4 段のキー | すべてのキー枠が実機のキーと重なる |
| **下段のキー** | ◇・Alt・スペースバーの境界が一致する（**Task A2 の計測の正否がここで決まる**） |

ずれていた場合は、写真からずれ量を読み取って Task A2 の計測値を修正し、テンプレートを作り直して再度照合する。

- [ ] **Step 5: 確定した寸法を文書化する**

`docs/hardware/dimensions.md` を作成し、以下を記録する。

- 公称値（294 / 108 / 手前20 / 奥32 / チルト 0・3・6°）とその出典
- 写真計測で確定した下段の構成（u 単位）
- 1:1 照合の結果（合格した根拠と、修正した場合はその経緯）
- 分割版の外形寸法（左右それぞれの幅・奥行）

- [ ] **Step 6: コミット**

```bash
git add tools/gen_template.py docs/hardware/dimensions.md
git commit -m "feat: 1:1 照合テンプレートで寸法を確定"
```

---

## フェーズ B: 機構設計

**このフェーズの目的は、私（エージェント）の CAD 能力が実用に足るかを早期に判定すること。** 最後に手に取れる実物が出る。ここで駄目なら、機構設計だけを別の手段（既製ケースの流用、外注、ユーザー自身の設計）に切り替える。基板を1枚も作らないうちに判断できる。

### Task B1: スイッチプレートの設計

最も単純で、かつ寸法精度が最も効く部品から始める。プレートが合っていればキーが正しい位置に来る。

**Files:**
- Create: `tools/gen_plate.py`
- Create: `tools/verify.py`
- Create: `tools/test_plate.py`

**Interfaces:**
- Consumes: `tools/layout.py` の `load_layout` / `bounds_mm`。
- Produces: `tools/verify.py` の `render(shape_or_mesh, out_png, views=...)` と `assert_no_interference(a, b)`。Task B3・B4 が使う。
- Produces: `build/plate_left.stl` / `build/plate_right.stl` / 同 `.dxf`。

- [ ] **Step 1: 自己検証モジュールを書く**

`tools/verify.py`:

```python
"""CAD 出力を 3 つの方法で検証する。

1. 寸法アサーション: バウンディングボックス・体積が想定どおりか
2. 干渉チェック: 2 つの形状のブーリアン積の体積が 0 か
3. レンダリング: PNG に落として人（またはエージェント）が目視する
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import trimesh
from build123d import Mode, export_stl
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

BUILD = Path(__file__).resolve().parent.parent / "build"


def to_mesh(part, name):
    """build123d の形状を STL 経由で trimesh に変換する。"""
    BUILD.mkdir(exist_ok=True)
    stl = BUILD / f"{name}.stl"
    export_stl(part, str(stl))
    return trimesh.load(str(stl)), stl


def assert_watertight(mesh, name):
    assert mesh.is_watertight, f"{name}: STL が水密でない（印刷できない）"


def assert_bbox(part, expect_x=None, expect_y=None, expect_z=None, tol=0.05):
    bb = part.bounding_box()
    for axis, expected in (("X", expect_x), ("Y", expect_y), ("Z", expect_z)):
        if expected is None:
            continue
        actual = getattr(bb.size, axis)
        assert abs(actual - expected) < tol, (
            f"{axis} が想定と違う: {actual:.3f} (期待 {expected:.3f})"
        )


def assert_no_interference(a, b, label="", tol_mm3=1e-3):
    """2 つの形状が干渉しないことを、ブーリアン積の体積で検証する。"""
    from build123d import Part

    common = Part(a.intersect(b).wrapped) if hasattr(a, "intersect") else None
    volume = 0.0 if common is None else common.volume
    assert volume < tol_mm3, f"{label}: 干渉している（重なり体積 {volume:.3f} mm^3）"


def render(mesh, out_png, views=((25, -60), (90, -90), (0, -90))):
    """複数視点で PNG に描画する。既定は 斜め / 真上 / 正面。"""
    fig = plt.figure(figsize=(5 * len(views), 5), dpi=140)
    b = mesh.bounds
    for i, (elev, azim) in enumerate(views, start=1):
        ax = fig.add_subplot(1, len(views), i, projection="3d")
        ax.add_collection3d(
            Poly3DCollection(mesh.triangles, facecolor="#b0c4de", edgecolor="none")
        )
        ax.set_xlim(b[0][0], b[1][0])
        ax.set_ylim(b[0][1], b[1][1])
        ax.set_zlim(b[0][2], b[1][2])
        ax.set_box_aspect(b[1] - b[0])
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        ax.set_title(f"elev={elev} azim={azim}", fontsize=8)
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    return out_png
```

- [ ] **Step 2: プレート生成スクリプトを書く**

`tools/gen_plate.py`:

```python
"""スイッチプレートを生成する。

MX 軸の標準開口は 14.0mm 角。プレート厚 1.5mm。
外形はキー外形を 3mm 外側にオフセットし、角を丸めたもの。
"""
import sys
from pathlib import Path

from build123d import (
    Axis, BuildPart, BuildSketch, Location, Locations, Mode,
    Rectangle, extrude, fillet,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout import bounds_mm, load_layout  # noqa: E402

SWITCH_CUTOUT = 14.0     # MX 標準
PLATE_THICKNESS = 1.5
EDGE_MARGIN = 3.0        # キー外形からプレート外形までの余白
CORNER_RADIUS = 3.0


def build_plate(keys):
    x0, y0, x1, y1 = bounds_mm(keys)
    w = (x1 - x0) + EDGE_MARGIN * 2
    h = (y1 - y0) + EDGE_MARGIN * 2
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2

    with BuildPart() as plate:
        with BuildSketch() as sk:
            Rectangle(w, h)
            fillet(sk.vertices(), radius=CORNER_RADIUS)
        extrude(amount=PLATE_THICKNESS)
        # スイッチ開口。KLE の Y は下向き、CAD の Y は上向きなので反転する。
        with Locations(
            *[Location((k.x_mm - cx, cy - k.y_mm, 0)) for k in keys]
        ):
            Box = Rectangle  # 2D で開けてから貫通させる
        with BuildSketch(plate.faces().sort_by(Axis.Z)[-1]) as holes:
            with Locations(*[(k.x_mm - cx, cy - k.y_mm) for k in keys]):
                Rectangle(SWITCH_CUTOUT, SWITCH_CUTOUT)
        extrude(amount=-PLATE_THICKNESS, mode=Mode.SUBTRACT)
    return plate.part, (w, h)


def main():
    for name in ("left", "right"):
        keys = [k for k in load_layout("layout/hhkb_split.json")]
        # 島の切れ目で左右に分ける（x の大きな飛びを境界とする）
        keys.sort(key=lambda k: k.x_mm)
        gaps = [
            i for i in range(1, len(keys))
            if keys[i].x_mm - keys[i - 1].x_mm > 30
        ]
        split_at = gaps[0] if gaps else len(keys)
        subset = keys[:split_at] if name == "left" else keys[split_at:]
        part, size = build_plate(subset)
        print(f"{name}: {len(subset)} keys, plate {size[0]:.1f} x {size[1]:.1f} mm")
        yield name, part, subset


if __name__ == "__main__":
    for name, part, subset in main():
        pass
```

**注意**: 上記は骨格。`build123d` の API は実行しながら詰める。`gen_plate.py` は Step 3 のテストが通るまで書き直してよい。

- [ ] **Step 3: プレートのテストを書いて走らせる**

`tools/test_plate.py`:

```python
"""プレートが物理的に正しいことを検証する。"""
from gen_plate import PLATE_THICKNESS, SWITCH_CUTOUT, build_plate
from layout import load_layout
from verify import assert_bbox, assert_watertight, to_mesh


def left_keys():
    keys = sorted(load_layout("layout/hhkb_split.json"), key=lambda k: k.x_mm)
    for i in range(1, len(keys)):
        if keys[i].x_mm - keys[i - 1].x_mm > 30:
            return keys[:i]
    raise AssertionError("左右の島の切れ目が見つからない")


def test_plate_thickness():
    part, _ = build_plate(left_keys())
    assert_bbox(part, expect_z=PLATE_THICKNESS)


def test_plate_is_watertight():
    part, _ = build_plate(left_keys())
    mesh, _ = to_mesh(part, "plate_left")
    assert_watertight(mesh, "plate_left")


def test_cutout_count_matches_key_count():
    """開口の数がキー数と一致すること。上面の穴の輪郭数で数える。"""
    keys = left_keys()
    part, _ = build_plate(keys)
    from build123d import Axis
    top = part.faces().sort_by(Axis.Z)[-1]
    inner_wires = len(top.inner_wires())
    assert inner_wires == len(keys), (
        f"開口数 {inner_wires} がキー数 {len(keys)} と一致しない"
    )


def test_cutout_size_is_14mm():
    """開口が 14.0mm 角であること。1 つ抜き出して寸法を測る。"""
    part, _ = build_plate(left_keys())
    from build123d import Axis
    top = part.faces().sort_by(Axis.Z)[-1]
    w = top.inner_wires()[0]
    bb = w.bounding_box()
    assert abs(bb.size.X - SWITCH_CUTOUT) < 0.01, f"開口 X: {bb.size.X}"
    assert abs(bb.size.Y - SWITCH_CUTOUT) < 0.01, f"開口 Y: {bb.size.Y}"
```

```bash
PYTHONPATH=tools .venv/bin/python -m pytest tools/test_plate.py -v
```

期待: 4 件すべて PASS。通らない間は `gen_plate.py` を直し続ける。

- [ ] **Step 4: レンダリングして目視する**

```bash
PYTHONPATH=tools .venv/bin/python -c "
from gen_plate import build_plate
from test_plate import left_keys
from verify import render, to_mesh
part, size = build_plate(left_keys())
mesh, stl = to_mesh(part, 'plate_left')
print(render(mesh, 'build/plate_left.png'))
"
```

**`build/plate_left.png` を Read ツールで開き、HHKB 左半分のプレートに見えることを確認する。** 開口の並び、行ずれ、Ctrl や Shift の幅広キーの位置が想定どおりか。ここで異常を見つけられなければ、自己検証の仕組みが機能していないということなので、レンダリング方法を見直す。

- [ ] **Step 5: コミット**

```bash
git add tools/gen_plate.py tools/verify.py tools/test_plate.py
git commit -m "feat: スイッチプレートの生成と自己検証を実装"
```

---

### Task B2: ボトムケースの設計

**Files:**
- Create: `tools/gen_case.py`
- Create: `tools/test_case.py`

**Interfaces:**
- Consumes: `tools/layout.py`、`tools/gen_plate.py` のプレート外形、`tools/verify.py`。
- Produces: `build/case_left.stl` / `build/case_right.stl`。Task B3 が印刷する。

- [ ] **Step 1: ケースの寸法パラメータを定義する**

`docs/hardware/dimensions.md` の確定値から、以下をスクリプト冒頭の定数として置く。

| パラメータ | 値 | 根拠 |
|---|---|---|
| 前縁の高さ | 20.0mm | ベース機の公称値 |
| 後縁の高さ | 32.0mm | ベース機の公称値 |
| 奥行 | 108.0mm | ベース機の公称値 |
| 傾斜角 | `atan((32-20)/108)` ≒ 6.34° | 上記から算出 |
| 壁厚 | 2.4mm | 0.4mm ノズル × 6 周。K1 Max が空隙なく充填できる厚み |
| 電池室 | 29.0 × 50.5 × 15.5mm | 単3 × 2 本 ＋ クリアランス 1mm |
| ネジ | M2、ボス外径 5.0mm、下穴 1.7mm | タッピングで留める |
| 三脚ナット | 1/4-20、埋込み用 座ぐり径 12.0mm・深さ 8.0mm | 市販の埋込みナット |

- [ ] **Step 2: ケース生成スクリプトを書く**

構成要素:
1. プレート外形と同じ輪郭を底面まで押し出したシェル（壁厚 2.5mm）
2. 上面をプレート厚のぶん座ぐり、プレートが面一に収まるようにする
3. 前縁 20mm・後縁 32mm の傾斜を、底面を斜めに切ることで作る
4. 奥側に電池室（29.0 × 50.5 × 15.5mm）を彫る
5. 電池蓋のスライド溝を彫る
6. 四隅と中央に M2 ボスを立てる
7. 底面に三脚ナットの座ぐりを彫る
8. ゴム足の座ぐりを 4 箇所彫る

- [ ] **Step 3: ケースのテストを書いて走らせる**

`tools/test_case.py` で以下を検証する。

```python
def test_case_front_and_rear_height():
    """前縁 20mm、後縁 32mm であること。"""

def test_battery_compartment_fits_aa():
    """電池室に単3 2 本（29.0 x 50.5 x 14.5mm）が干渉なく入ること。
    電池を表す直方体を作り、ケースとのブーリアン積が 0 であることを確認する。"""

def test_case_is_watertight():
    """印刷可能な形状であること。"""

def test_plate_fits_in_case():
    """プレートとケースが干渉しないこと（assert_no_interference）。"""

def test_wall_thickness_minimum():
    """最薄部が 2.0mm を下回らないこと。断面のオフセットで確認する。"""
```

```bash
PYTHONPATH=tools .venv/bin/python -m pytest tools/test_case.py -v
```

- [ ] **Step 4: レンダリングして目視する**

斜め・真上・正面・断面の 4 視点で PNG を出し、**Read ツールで開いて確認する**。特に見るべき点:

- 傾斜が手前から奥へ正しく付いているか（逆になっていないか）
- 電池室が奥側にあり、傾斜の厚い部分に収まっているか
- ボスがキーの直下に来て干渉していないか

- [ ] **Step 5: コミット**

```bash
git add tools/gen_case.py tools/test_case.py
git commit -m "feat: ボトムケースの生成と自己検証を実装"
```

---

### Task B3: 試作印刷と実機比較（判定タスク）

**Files:**
- Create: `docs/hardware/phaseB-results.md`

- [ ] **Step 1: 印刷用ファイルを出力する**

```bash
PYTHONPATH=tools .venv/bin/python tools/gen_plate.py
PYTHONPATH=tools .venv/bin/python tools/gen_case.py
ls -la build/*.stl
```

- [ ] **Step 2: 印刷を依頼する**

ユーザーへの依頼:

> `build/plate_left.stl` と `build/case_left.stl` を印刷してください。左半分だけで判定できます。素材は手持ちのもので構いません（PLA で十分）。積層 0.2mm、充填 20% 程度を想定しています。

プレートは薄いので反りやすい。反った場合はブリム付きで再印刷してもらう。

- [ ] **Step 3: 判定する**

印刷物と HHKB 実機を並べた写真を送ってもらい、**Read ツールで開いて**以下を判定する。

| # | 判定項目 | 合格条件 |
|---|---|---|
| 1 | プレートにスイッチが入る | MX スイッチ（あれば）またはキーキャップが開口に収まる |
| 2 | キー位置が HHKB と一致する | 実機の左半分に重ねて、キーの中心が揃う |
| 3 | ケースの傾斜が HHKB と一致する | 横から見て、実機と同じ角度に見える |
| 4 | プレートがケースに収まる | 手で嵌め合わせられる |
| 5 | 電池室に単3が2本入る | 実物の電池を入れて確認する |
| 6 | 全体の見た目 | HHKB を半分に切ったものに見える |

- [ ] **Step 4: フェーズ B の結論を出す**

`docs/hardware/phaseB-results.md` を作成する。

```markdown
# フェーズB 結果: CAD による機構設計の実現可能性

## 判定結果

（Step 3 の 6 項目それぞれの合否と、写真から読み取れたずれ）

## 結論

- [ ] **合格** — CAD で機構設計を続行する。フェーズ C（電気検証）へ進む
- [ ] **要修正** — 修正内容と、修正後の再印刷で解決する見込み
- [ ] **不合格** — 機構設計を別の手段に切り替える

## 不合格の場合の代替案

1. 既製の分割キーボードケースを流用し、配列だけ合わせる
2. ケースを外注設計する
3. ケースを諦め、プレートサンドイッチ（FR4 2 枚 ＋ スペーサー）にする
   — 機構設計がほぼ不要になり、JLCPCB で全部作れる

## 積み残し

（フェーズ D・E へ持ち越す事項）
```

- [ ] **Step 5: コミット**

```bash
git add docs/hardware/phaseB-results.md
git commit -m "docs: フェーズB の判定結果"
```

---

## 全体の順序

| フェーズ | 内容 | 計画 | 状態 |
|---|---|---|---|
| A | 寸法確定と配列のデータ化 | 本ドキュメント | 未着手 |
| B | 機構設計（CAD）と試作印刷 | 本ドキュメント | 未着手 |
| C | 電気・ファームウェア検証 | [phaseC](2026-08-05-phaseC-electrical-firmware-validation.md) | 未着手 |
| D | PCB 設計・発注 | 未作成（フェーズ B・C の結果を入力に作る） | — |
| E | 組立・統合 | 未作成 | — |
