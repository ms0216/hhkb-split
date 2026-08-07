# XIAO nRF52840 の書き込みトラブルと復旧手順

**2026-08-07 に実際に遭遇し、解決した記録。**

Task C1 の疎通確認で「書き込んだのに何も起きない」状態に 2 時間ほど費やした。
原因も手順も再現できる形で残す。**新品の XIAO では起きない問題**だが、
中古や転用品を使うときは必ず踏む。

---

## 1. 症状

- `.uf2` をドライブへコピーすると、macOS が**エラーコード -36** を出す
- コピー後、XIAO は USB に**まったく現れない**（HID もシリアルも無し）
- RESET 2 回でブートローダには入れる（ドライブはマウントされる）
- ブートローダは `SoftDevice: not found` と表示していた

---

## 2. 診断: フラッシュを読み返す

**書き込みツールの「成功」報告を信用しない。** UF2 ブートローダは
`CURRENT.UF2` として**現在のフラッシュ内容を読み出せる**ので、
実際に何が入っているかを確認できる。これが決め手だった。

```bash
cp /Volumes/XIAO-SENSE/CURRENT.UF2 ./current.uf2
```

UF2 は 512 バイト単位のブロックで、各ブロックの先頭 32 バイトに
書き込み先アドレスが入っている。これを解いてアドレスごとの中身を並べれば、
フラッシュのどこに何があるかが分かる。

```python
import struct

def blocks(path):
    """UF2 を「書き込み先アドレス → 中身 256 バイト」の辞書にする。"""
    data = open(path, "rb").read()
    out = {}
    for i in range(len(data) // 512):
        b = data[i * 512:(i + 1) * 512]
        magic, _, _, addr, size, _, _, _ = struct.unpack("<8I", b[:32])
        if magic == 0x0A324655:              # UF2 のマジック
            out[addr] = b[32:32 + size]
    return out
```

これで次の 3 つを確かめる。

| 確認 | 正常な値 |
|---|---|
| データのある区間 | 0x1000〜0x27000 に SoftDevice、0x27000 以降にアプリ |
| SD 情報構造体（0x3000 + 0x04） | magic = `0x51B1E5DB`、SD_SIZE = `0x27000` |
| アプリのベクタテーブル（0x27000） | SP が RAM 域（0x2000xxxx）、PC がアプリ域 |

書き込んだ `.uf2` のブロックと読み返した内容を照合すれば、
**何ブロック書けたか**が正確に分かる。

---

## 3. 原因

この XIAO は以前 **nRF Sniffer** 用に使われており、その際に
**SoftDevice（0x1000〜0x27000）が消されて**いた。

nRF52840 の起動は次の順で進む。

```
MBR (0x0) → ブートローダ → SoftDevice のサイズを読む → アプリへ飛ぶ
                                    ↑
                        ここが壊れているとアプリに到達しない
```

ブートローダは SD 情報構造体から `SD_SIZE` を読み、それをアプリの開始位置と
みなす。ZMK の `.uf2` は 0x27000 を狙って書かれるので、**SoftDevice が
正常でないとアプリは絶対に起動しない**。

読み返した結果、SoftDevice は 152,728 バイトのうち **12KB しか書けていなかった**。
たまたま情報構造体（0x3000）だけが書けていたため、ブートローダは
「S140 7.3.0 あり」と表示しており、**表示は当てにならなかった**。

---

## 4. 復旧手順

### 用意

```bash
python3 -m venv dfuenv
./dfuenv/bin/pip install adafruit-nrfutil
```

SoftDevice のバイナリは Adafruit のブートローダ配布物から取り出せる。

```bash
curl -sLO https://github.com/adafruit/Adafruit_nRF52_Bootloader/releases/download/0.11.0/xiao_nrf52840_ble_bootloader-0.11.0_s140_7.3.0.zip
unzip -o xiao_nrf52840_ble_bootloader-0.11.0_s140_7.3.0.zip -d pkg
# pkg/sd_bl.bin の先頭 152728 バイトが SoftDevice（0x1000 から配置）
```

### SoftDevice だけのパッケージを作る

**ブートローダは含めない。** ブートローダの書き換えは失敗すると SWD デバッガ
なしでは復旧できなくなるが、SoftDevice だけなら失敗してもブートローダは無傷。

```bash
# sd_bl.bin の先頭 152728 バイトを 0x1000 起点の Intel HEX に変換してから
adafruit-nrfutil dfu genpkg \
    --dev-type 82 --dev-revision 52840 --sd-req 0xFFFE \
    --softdevice s140.hex sd_only.zip
```

### 書き込む

RESET を素早く 2 回押してブートローダに入り、シリアルポートを確認して実行する。

```bash
adafruit-nrfutil --verbose dfu serial \
    --package sd_only.zip -p /dev/tty.usbmodem1101 -b 115200
```

**`--singlebank` は付けない。** 最初に `--singlebank` 付きで
「ブートローダ＋SoftDevice」を書いたときは `Device programmed.` と報告された
にもかかわらず 12KB しか書けていなかった。デュアルバンク（既定）は
いったん別領域に受け取ってから MBR がまとめて配置するので確実だった。

### 確認する

**必ず読み返す。** 手順 2 の方法で 597 ブロックすべてが一致することを確認する。
一致したら `.uf2` を書き込み直す（デュアルバンクの一時領域がアプリ側を
上書きしているため）。

---

## 5. macOS 固有の紛らわしい挙動

| 現象 | 意味 |
|---|---|
| **エラーコード -36** | 正常。書き込み完了で XIAO が再起動しドライブが消えたため |
| **`cp: ... Device not configured`** | 同上。ターミナルの `cp` でも出るが無害 |
| **「ディスクの不正な取り出し」通知** | 同上。むしろ**書き込みが受理された証拠** |
| **`INFO_UF2.TXT` の内容が古いまま** | Finder がキャッシュしている。挿し直すと更新される |
| **`!registered, !matched`** | macOS がドライバを割り当てていない。**「アクセサリの接続を許可しますか？」を許可する** |
| **キーボード設定アシスタントが開く** | 正常。治具はキーが 2 個しかないので応えられない。閉じてよい |

`ioreg` で状態を見るのが確実。

```bash
ioreg -p IOUSB -w0 -l | grep '"USB Product Name"'
ioreg -p IOUSB -w0                      # ツリーと registered/matched の状態
```

ZMK が動いていれば **`kUSBVendorString = "ZMK Project"`**、
製品名は `CONFIG_ZMK_KEYBOARD_NAME` の値になる。

---

## 6. 教訓

**ツールの成功報告を信用せず、書いたものを読み返す。**
`Device programmed.` と表示され、進捗バーも最後まで伸び、所要 20.6 秒と
出ていたが、実際には 8% しか書けていなかった。フラッシュを読み返すまで
2 回の書き込みを無駄にした。

これは CAD で「Python が通った」ことと「形が正しい」ことを分けて検証したのと
同じ話で、**書けたことと書き込みが成った ことは別**だった。
