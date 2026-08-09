"""CPL の回転補正だけを取り出したもの。

`export_fab.py` は pcbnew を import するので **KiCad の Python でしか
動かない**。回転の規則は検査したいので、ここに分けてある。
export_fab.py はここから読む。

**KiCad のフットプリントの向きと JLCPCB のライブラリの向きは一致しない。**
補正せずに出すと部品が 90/180 度ずれて載る。ダイオード 61 個が逆向きなら
基板は使えない。

出典: matthewlai/JLCKicadTools の cpl_rotations_db.csv（2026-08-09 取得）。
"""

# フットプリント名の接頭辞 → 補正角（度）
ROTATION_DB = {
    "TSSOP-": 270,
}

# **補正表に無く、向きを確認していないフットプリント。**
# 発注ページの配置プレビューで目視確認する対象。
# 2 端子の受動部品（0805/1206）は向きが無いので確認不要。
ROTATION_UNVERIFIED = ("Hirose_FH12", "SW_Hotswap_Kailh")


def rotation_for_jlcpcb(footprint, rot_deg, bottom):
    """KiCad の回転を JLCPCB の CPL の回転へ直す。

    2 段階ある。

      1. ライブラリの向きの差を補正する。**裏面は符号が逆**
         （裏から見ると反時計回りが負になる。KiCad 側の都合）
      2. 裏面はさらに `(-rot + 180) % 360`
         （JLCPCB 側の都合。過去に何度も変わっており、いまはこれ）
    """
    corr = next((v for k, v in ROTATION_DB.items() if footprint.startswith(k)), 0)
    rot = (rot_deg - corr) % 360 if bottom else (rot_deg + corr) % 360
    if bottom:
        rot = (-rot + 180) % 360
    return rot % 360
