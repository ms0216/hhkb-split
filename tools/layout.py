"""KLE JSON を読み、キーごとの実寸座標(mm)に変換する。

このモジュールが配列の唯一の入口。テンプレート・プレート・ケース・PCB は
すべてここを経由するので、配列を変えたら全部が追従する。

KLE の書式で押さえるべき点:
  - 行は配列。文字列がキー、辞書は「次のキーに適用する属性」
  - `x` / `y` は「現在位置からの相対移動」で、累積する
  - `w` / `h` は **そのキー1つだけ** に効き、キーを置くと 1 に戻る
  - 先頭のメタデータ辞書（行ではなく単独の辞書）は読み飛ばす
"""

import json
from dataclasses import dataclass
from pathlib import Path

UNIT = 19.05


@dataclass(frozen=True)
class Key:
    """キー1つ。座標はキー中心、原点は配列の左上、Y は下向きが正。"""

    x_mm: float
    y_mm: float
    w_u: float
    h_u: float
    label: str

    @property
    def w_mm(self) -> float:
        return self.w_u * UNIT

    @property
    def h_mm(self) -> float:
        return self.h_u * UNIT

    @property
    def left_u(self) -> float:
        return self.x_mm / UNIT - self.w_u / 2

    @property
    def right_u(self) -> float:
        return self.x_mm / UNIT + self.w_u / 2

    @property
    def row(self) -> int:
        return round(self.y_mm / UNIT - 0.5)


def load_layout(path) -> list[Key]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    keys: list[Key] = []
    y = 0.0
    for row in raw:
        if not isinstance(row, list):
            continue                      # 先頭のメタデータ辞書
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
                    x_mm=(x + w / 2) * UNIT,
                    y_mm=(y + h / 2) * UNIT,
                    w_u=w,
                    h_u=h,
                    label=str(item),
                )
            )
            x += w
            w = h = 1.0                   # 属性は1キーで失効する
        y += 1.0
    return keys


def bounds_mm(keys: list[Key]) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) をキーの外形で返す。"""
    return (
        min(k.x_mm - k.w_mm / 2 for k in keys),
        min(k.y_mm - k.h_mm / 2 for k in keys),
        max(k.x_mm + k.w_mm / 2 for k in keys),
        max(k.y_mm + k.h_mm / 2 for k in keys),
    )


def split_halves(keys: list[Key], gap_u: float = 1.0) -> tuple[list[Key], list[Key]]:
    """x 方向の大きな空きを境に左右の島へ分ける。

    分割版の JSON は左右を離して置いてあるので、その空きを検出して分ける。
    """
    ordered = sorted(keys, key=lambda k: k.left_u)
    reach = ordered[0].right_u
    for i in range(1, len(ordered)):
        if ordered[i].left_u - reach >= gap_u:
            return ordered[:i], ordered[i:]
        reach = max(reach, ordered[i].right_u)
    raise ValueError("左右の島の切れ目が見つからない")
