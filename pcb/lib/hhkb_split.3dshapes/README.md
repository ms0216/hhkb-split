# 3D モデルの出所

| ファイル | 出所 | 取得日 |
|---|---|---|
| `XIAO_nRF52840.step` | **Seeed Studio 公式配布**（wiki の Resources）。<https://files.seeedstudio.com/wiki/XIAO-BLE/seeed-studio-xiao-nrf52840-3d-model.zip> 内の `XIAO-nRF52840 v15.step` を改名したもの（中身は無改変） | 2026-08-10 |

- 実測（2026-08-08・ノギス）21×18×3 / USB 込み 4.5mm に対し、モデルは
  20.95×17.78 / 4.46mm。**一致を確認してから採用した**
  （選定基準は docs/hardware/decisions/2026-08-09-third-party-3d-models.md）
- フットプリント `hhkb_split.pretty/XIAO_nRF52840.kicad_mod` の
  `(model ...)` から `${KIPRJMOD}/lib/hhkb_split.3dshapes/` で参照される。
  向きとオフセットは STEP 出力の実測で合わせた（基板中心＝アンカー。
  キャステレーションの並びからパッド基準とも一致）
- 確定値: `(offset (xyz 6.111 -1.804 0.165)) (rotate (xyz -90 0 -90))`。
  **合わせるときは USB シェルの立体（4.2×7.3×8.94mm）を寸法で特定して
  位置を見ること。**bbox の端から推測して一度 180° 逆に置いた
  （利用者が Blender で発見。向きの検査は test_assembly にある）
