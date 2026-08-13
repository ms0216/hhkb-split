"""アンテナの門の**判定だけ**を取り出したもの。

`export_fab.py` は pcbnew を import するので **KiCad の Python でしか
動かない**。門の規則は検査したいので、ここに分けてある
（`export_fab_rotation.py` と同じ理由・同じ流儀）。

**なぜ分けたか。**もとは検査側（`test_export_fab_gate.py`）が
`_UNRESOLVED` / `_ACCEPTED` の文字列を**自前で二重定義**し、
それが export_fab.py のソースに含まれるかを見ていた。
**両方とも自分で書いた文字列なので、規則そのものが間違っていても通る**
（CLAUDE.md 規則 3「自分の生成物どうしの一致は検証ではない」）。
いまは検査もここの実物を import して、**挙動**で確かめる。
"""

import re

# #23 が未解決であることを示す見出し。これが消えたら門は不要になる。
UNRESOLVED_HEADING = "## 23. ★未解決★ アンテナが地板に挟まれている"

# 承知の記録。**行頭から始まる見出しであること。**
# 本文が鉤括弧の中で引用しても開かないようにするための ^...$。
# （2026-08-11、門を説明する散文そのものが門を開けていた）
ACCEPTED_HEADING_RE = r"^### 承知して発注する\s*$"


def is_gate_open(doc):
    """open-gaps.md の中身を見て、発注してよいかを返す。

    True なら通す（#23 が解決した、または承知の節が見出しとして在る）。
    False なら止める。
    """
    if UNRESOLVED_HEADING not in doc:
        return True                             # 解決済み
    return re.search(ACCEPTED_HEADING_RE, doc, re.M) is not None
