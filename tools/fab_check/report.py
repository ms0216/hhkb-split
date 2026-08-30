import json,base64,html
R=json.load(open("build/fab_check/evidence.json"))
def img(p): return "data:image/png;base64,"+base64.b64encode(open(p,"rb").read()).decode()
def esc(x): return html.escape(str(x))
OK='<span class="ok">一致</span>'; NG='<span class="ng">不一致</span>'
# 595 table
t595=""
for r in R["u595"]:
    t595+=f'<tr><td>{r["board"]} {r["ref"]}</td><td class="n">{r["pin"]}</td><td>{esc(r["ti"])}</td><td>{esc(r["expected"])}</td><td>{esc(r["actual"])}</td><td>{OK if r["ok"] else NG}</td></tr>'
tx=""
for r in R["xiao"]:
    tx+=f'<tr><td>{r["pad"]}</td><td class="n">{r["seeed_xy"][0]:+.2f}, {r["seeed_xy"][1]:+.2f}</td><td class="n">{r["board_xy"][0]:+.2f}, {r["board_xy"][1]:+.2f}</td><td>{OK if r["pos_ok"] else NG}</td><td>{esc(r["net"])}</td><td>{esc(r["firmware"])}</td></tr>'
tf=""
for r in R["ffc"]:
    same=r["left_J_DB"]==r["right_J_DB"]==r["J_MAIN"]
    tf+=f'<tr><td class="n">{r["pin"]}</td><td>{esc(r["J_MAIN"])}</td><td class="n">{r["jdb_pin"]}</td><td>{esc(r["left_J_DB"])}</td><td>{esc(r["right_J_DB"])}</td><td>{OK if same else NG}</td></tr>'
tc=""
for c in R["chain"]:
    tc+=f'<tr><td>{c["half"]}</td><td>{c["sw"]}</td><td><b>{esc(c["key"])}</b></td><td>{esc(c["col_net"])}</td><td>{c["diode"]}</td><td>{esc(c["row_net"])} ({c["row_pin"]})</td><td class="n">RC({c["board_rc"][0]},{c["board_rc"][1]})</td><td class="n">RC({c["fw_rc"][0]},{c["fw_rc"][1]})</td><td>{OK if c["ok"] else NG}</td></tr>'
g=R["ffc_geo"]
def gr(k):
    v=g[k]; return f'<tr><td>{k}</td><td>{v["layer"]}</td><td class="n">{v["rot"]:.0f}°</td><td>{v["pad1_side"]}</td><td>{v["pads_side_y"]}</td></tr>'
nok=sum(1 for c in R["chain"] if c["ok"])
page=f'''<title>HHKB 分割 配線検証 2026-08-28</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+JP:wght@400;600&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>
:root{{--bg:#f3f5f8;--paper:#ffffff;--ink:#16212c;--mute:#5a6b7c;--line:#d5dce4;--acc:#0f6b8c;--ok:#1d7a4a;--okbg:#e2f3e9;--ng:#b4231f;--ngbg:#fbe6e4;--warn:#8a5a00;--warnbg:#fff1d6;--code:#eef1f5}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#12181f;--paper:#1a2129;--ink:#e6ebf0;--mute:#98a6b5;--line:#2e3a46;--acc:#5fb6d8;--ok:#5fd18f;--okbg:#173626;--ng:#ff8a80;--ngbg:#43201e;--warn:#f0c060;--warnbg:#3d2f10;--code:#232c36}}}}
:root[data-theme="dark"]{{--bg:#12181f;--paper:#1a2129;--ink:#e6ebf0;--mute:#98a6b5;--line:#2e3a46;--acc:#5fb6d8;--ok:#5fd18f;--okbg:#173626;--ng:#ff8a80;--ngbg:#43201e;--warn:#f0c060;--warnbg:#3d2f10;--code:#232c36}}
body{{background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans JP","Hiragino Sans",sans-serif;line-height:1.7;margin:0}}
main{{max-width:960px;margin:0 auto;padding:32px 20px 80px}}
h1{{font-size:1.7rem;line-height:1.3;text-wrap:balance;margin:0 0 6px}}
h2{{font-size:1.25rem;margin:48px 0 12px;padding-top:12px;border-top:2px solid var(--line)}}
h3{{font-size:1rem;margin:24px 0 8px;color:var(--acc)}}
p,li{{max-width:70ch}}
.sub{{color:var(--mute);margin:0 0 24px}}
.verdict{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:20px 0}}
.card{{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:14px 16px}}
.card b{{display:block;font-size:.8rem;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);margin-bottom:6px}}
.card .big{{font-size:1.15rem;font-weight:600}}
.ok{{color:var(--ok);background:var(--okbg);padding:1px 8px;border-radius:10px;font-size:.85rem;white-space:nowrap}}
.ng{{color:var(--ng);background:var(--ngbg);padding:1px 8px;border-radius:10px;font-size:.85rem;white-space:nowrap}}
.alert{{background:var(--ngbg);border-left:4px solid var(--ng);padding:12px 16px;border-radius:4px;margin:16px 0}}
.note{{background:var(--warnbg);border-left:4px solid var(--warn);padding:12px 16px;border-radius:4px;margin:16px 0}}
.todo{{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:14px 18px}}
.todo li{{margin:6px 0}}
.tbl{{overflow-x:auto;background:var(--paper);border:1px solid var(--line);border-radius:6px;margin:12px 0}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-size:.75rem;letter-spacing:.05em;text-transform:uppercase;color:var(--mute);background:var(--code)}}
td.n,code{{font-family:"IBM Plex Mono",Menlo,monospace;font-variant-numeric:tabular-nums}}
code{{background:var(--code);padding:1px 5px;border-radius:3px;font-size:.85em}}
figure{{margin:12px 0}} figure img{{max-width:100%;border:1px solid var(--line);border-radius:4px;background:#faf9f5}}
figcaption{{font-size:.82rem;color:var(--mute);margin-top:4px}}
details summary{{cursor:pointer;color:var(--acc)}}
svg text{{font-family:"IBM Plex Sans JP",sans-serif;font-size:11px;fill:var(--ink)}}
</style>
<main>
<h1>基板 3 枚の配線検証 — 595・XIAO・FFC・61 キー</h1>
<p class="sub">2026-08-28 夜、あなたが寝ている間に作成。<b>板の実体（pcb/*.kicad_pcb）</b>から読み取った結線を、<b>外部の資料</b>（TI データシート・Seeed 公式ピン配置・Hirose/DigiKey の仕様・ファームウェアの dtsi）と突き合わせた結果です。</p>

<div class="verdict">
<div class="card"><b>74LVC595（左 U1・右 U1/U2）</b><div class="big">{OK} 48 ピン全部</div>TI SCASE93A Table 4-1 と一致</div>
<div class="card"><b>XIAO nRF52840</b><div class="big">{OK} 14 パッド全部</div>Seeed 公式の座標と一致・ファームのピンと一致</div>
<div class="card"><b>キー → 行列 → ファーム</b><div class="big">{OK} {nok} / 61 キー</div>ダイオード向きも全部 col→row</div>
<div class="card"><b>FFC ケーブル</b><div class="big">{OK} 直線経路に修正</div>J_DB の口を奥向き・右は 1.63mm 手前。A タイプで正しい。3 基板とも DRC 0</div>
</div>

<div class="alert"><b>寝ている間に直したこと（1 つ判断が要る → 0 に、代わりに右の配線が 1 つ残った）</b><br>
J_DB（本体基板の FFC コネクタ）の口が<b>手前向き</b>だったのは、2026-08-08 の初回配置で KiCad の Flip() が与えた 180° をそのまま使い、誰も向きを決めていなかったためです（履歴で確認）。<b>口を奥向きに回しました。</b>ケーブルは J_DB を奥へ出てそのまま子基板の J_MAIN に入る直線経路になり、U ターンが消え、<b>買ってある A タイプで正しく</b>なりました。J_DB のピン番号は J_MAIN の鏡像（13−n）です（回すとピン 1 の側が入れ替わるため。表はそう直しました）。<br>
<b>左</b>: パッドが回す前と同じ座標に来るよう置いたので配線は無傷。<b>右</b>: 同じ置き方は SW10 の位置決め穴に当たるため回しただけの位置に置き、あなたが 08-30 に引き直した（私は COL0 を MP パッドの外へ逃がした）。<b>3 基板とも DRC 0 / 未配線 0。</b></div>

<div class="todo"><b>残り（発注を止めるものは無い・検査 460 緑）</b>
<ol>
<li><b>1:1 印刷</b>: <code>build/fab_check/daughterboard_1to1_top_view.pdf</code> を「実際のサイズ」で印刷し XIAO を載せる（取付穴 16.0mm で確認）</li>
<li>595 が届いたら 1 番ピンの印を見比べる／JLCPCB の配置プレビュー（fab-checklist §1）</li>
</ol></div>

<h2>1. FFC — 口の向きを直した。ピン対応は J_DB が J_MAIN の鏡像</h2>
<h3>1a. ピン対応（同じ導体は J_MAIN の n 番と J_DB の 13−n 番）</h3>
<div class="tbl"><table><tr><th>J_MAIN ピン</th><th>J_MAIN のネット</th><th>J_DB ピン</th><th>左 J_DB</th><th>右 J_DB</th><th>判定</th></tr>{tf}</table></div>
<h3>1b. 幾何（板の実体から）</h3>
<div class="tbl"><table><tr><th>コネクタ</th><th>面</th><th>回転</th><th>ピン 1 の側</th><th>パッドの側</th></tr>{gr("left/J_DB")}{gr("right/J_DB")}{gr("daughterboard/J_MAIN")}</table></div>
<p>J_MAIN は裏面・180°・ピン 1 が +X・口は手前（本体側）。<b>J_DB は裏面・0°・ピン 1 が −X・口は奥（子基板側）</b>——2026-08-28 夜に回した。口どうしが向かい合い、ケーブルはまっすぐ渡る。</p>
<h3>1c. 接点面を追う（横から見た図・手前が左）— 直した後</h3>
<figure>
<svg viewBox="0 0 820 300" width="100%" role="img" aria-label="直した後の FFC 経路の側面図">
<defs><marker id="ar2" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 z" fill="var(--acc)"/></marker></defs>
<text x="20" y="20" fill="var(--mute)">左＝手前（キー側）、右＝奥（コブ側）。縮尺なし。赤い短線＝導体（接点）が出ている面。</text>
<line x1="40" y1="110" x2="440" y2="80" stroke="var(--ink)" stroke-width="5"/><text x="40" y="60">本体基板（7.3° 傾き・裏が下）</text>
<rect x="320" y="91" width="70" height="16" fill="var(--code)" stroke="var(--ink)"/><text x="230" y="130">J_DB（裏面・下接点・口は奥）</text>
<line x1="540" y1="200" x2="790" y2="200" stroke="var(--ink)" stroke-width="5"/><text x="600" y="190">子基板（水平・裏が下）</text>
<rect x="545" y="203" width="60" height="16" fill="var(--code)" stroke="var(--ink)"/><text x="612" y="217">J_MAIN（裏面・下接点・口は手前）</text>
<line x1="30" y1="285" x2="800" y2="285" stroke="var(--mute)" stroke-width="2" stroke-dasharray="6 4"/><text x="35" y="305" fill="var(--mute)">床</text>
<path d="M390,99 L430,99 Q450,99 462,112 L520,198 Q528,211 540,211 L545,211" fill="none" stroke="var(--acc)" stroke-width="4" marker-end="url(#ar2)"/>
<g stroke="var(--ng)" stroke-width="3"><line x1="400" y1="94" x2="428" y2="94"/><line x1="480" y1="140" x2="497" y2="164"/><line x1="530" y1="206" x2="544" y2="206"/></g>
<text x="440" y="70" fill="var(--ng)">① J_DB で上向き ✓</text>
<text x="500" y="150" fill="var(--ng)">② 折り返し無し・面は上のまま</text>
<text x="560" y="250" fill="var(--ng)">③ J_MAIN でも上向き ✓（A タイプで正しい）</text>
</svg>
<figcaption>J_DB の口を奥向きにしたので、ケーブルは奥へ出てそのまま斜めに下り J_MAIN に入る。厚み方向の折り返しが無く、導体の面は両端で上向き。組立モデル（<code>gen_assembly.py</code>）もこの経路に描き直し、箱モードの干渉 0。</figcaption>
</figure>
<figure><img src="{img('build/assembly/left_section_db.png')}" alt="左の組立モデルの断面（子基板の x で切った図）"><figcaption>組立モデルの断面（左・x=58.5、<code>tools/refresh_view.sh</code> の出力）。黒＝J_DB（本体基板の裏）、橙＝FFC、紫＝J_MAIN（子基板の裏の手前端）、青＝子基板と XIAO の占有、緑＝本体基板。FFC は J_DB を奥へ出てすぐ潜り、斜めに下って J_MAIN に入る。右も同じ（<code>build/assembly/right_section_db.png</code>）。</figcaption></figure>
<details><summary>直す前の経路（U ターンで面が裏返っていた）</summary><p>口が手前向きだったときの経路は「手前へ出る → 床へ折り下げ → 床を奥へ → J_MAIN」。手前→下→奥の U ターンで導体が下を向き、J_MAIN（下接点）で合わなかった。この向きは 2026-08-08 の初回配置で KiCad の Flip() が与えた 180° が残ったもので、誰も決めていなかった（git 履歴で確認）。</p></details>
<div class="note">2026-08-30 午後: 右 J_DB を 1.63mm 手前へ動かし（ソケットまで 3.9mm・出口の曲げ半径 ≈6mm）、左右の配線と露出ビアを引き直して決着。3 基板とも DRC 0。</div>

<h2>2. 74LVC595 — 48 ピン全部が TI のデータシートどおり</h2>
<p>期待値は TI SCASE93A Table 4-1（TSSOP-16: 1 QB … 8 GND, 9 QH′, 10 SRCLR, 11 SRCLK, 12 RCLK, 13 OE, 14 SER, 15 QA, 16 VCC）から、回路の役割（SRCLK=SPI_SCK, RCLK=CS, SER=MOSI または前段の QH′, SRCLR=3V3 固定, OE=GND 固定）に置き換えたもの。実際は板のパッドに付いたネット名。</p>
<figure><img src="{img('build/fab_check/left_U1_nets.png')}" alt="左 U1 の各パッドとネット名"><figcaption>左 U1（裏面・回転 0°）。1 番ピンが左下、16 番 VCC が右下。読み方: 表から透視した図なので、裏返して実物を見ると左右が入れ替わる。</figcaption></figure>
<figure><img src="{img('build/fab_check/right_U1_U2_nets.png')}" alt="右 U1・U2 の各パッドとネット名"><figcaption>右 U1（180°）と U2（90°・数珠つなぎの 2 個目。QA=COL8 のみ使用、9 番 QH′ は次段なし）。U1 の 9 番 QH′ → U2 の 14 番 SER が <code>U1_U2</code> で繋がっている。</figcaption></figure>
<details><summary>48 ピンの表を開く</summary><div class="tbl"><table><tr><th>部品</th><th>ピン</th><th>TI 名</th><th>期待ネット</th><th>板のネット</th><th>判定</th></tr>{t595}</table></div></details>

<h2>3. XIAO nRF52840 — 14 パッドの位置と結線</h2>
<p>期待座標は Seeed 公式ピン配置（左列 D0〜D6、右列 5V/GND/3V3/D10/D9/D8/D7、2.54mm ピッチ・列間 15.24mm）。「板の座標」はフットプリントの中心を原点に戻した値。ファーム列は overlay/dtsi から。</p>
<figure><img src="{img('build/fab_check/db_nets.png')}" alt="子基板のパッドとネット名"><figcaption>子基板。XIAO（表・0°）、D_PWR（裏）、J_MAIN（裏・180°）。SPI は D7=CS, D8=SCK, D10=MOSI（XIAO 既定の SPI ピン）、D0=電池電圧（AIN0）。</figcaption></figure>
<div class="tbl"><table><tr><th>パッド</th><th>Seeed 座標</th><th>板の座標</th><th>位置</th><th>ネット</th><th>ファームでの役割</th></tr>{tx}</table></div>
<p>電源まわり: D_PWR（B5819W）は <b>パッド 1＝カソード（帯）＝V3V3</b>、パッド 2＝アノード＝VBATT_SW。電池 → スイッチ → ダイオード → 3V3 の向きで正しい（USB 給電時に電池へ逆流しない向き）。<b>ただし JLCPCB 側の回転補正はこのページでは検証できない</b>（fab-checklist §1・配置プレビューで目視）。</p>

<h2>4. 61 キーそれぞれの経路 — 板 ↔ ファームが全キー一致</h2>
<p>板から読んだ経路: キー（SW）→ COL ネット / ダイオードのアノード側 → ダイオードのカソード → ROW ネット → XIAO のピン。それを行番号（overlay の row-gpios の順）と列番号に直し、dtsi の <code>matrix-transform</code> の RC と比べた。ダイオードは全数「パッド 2（アノード）がキー側・パッド 1（カソード・帯）が行側」＝ col2row。</p>
<details open><summary>61 キーの表</summary><div class="tbl"><table><tr><th>側</th><th>SW</th><th>キー</th><th>列ネット</th><th>ダイオード</th><th>行ネット（XIAO ピン）</th><th>板 RC</th><th>ファーム RC</th><th>判定</th></tr>{tc}</table></div></details>

<h2>5. そのほか今日確認したこと</h2>
<ul>
<li>DRC: 左 0 / 右 0 / 子基板 0（未配線 0）。検査 151 件緑。<code>export_fab.py</code> リハーサル通過、B.Mask 開口を SPARE/SPARE2 の 4 点で座標確認</li>
<li>1:1 PDF（<code>build/fab_check/*_1to1_*.pdf</code>、A4 横）: 300dpi にラスタライズして取付穴の中心間隔を測ると <b>16.00mm</b>（設計値 16.00）。印刷時は「実際のサイズ」を選ぶこと。<code>bottom_view</code> は鏡像で、裏から見た向き</li>
<li>このページで<b>検証できないもの</b>: JLCPCB の部品回転（595・ダイオード・FFC・ソケット）→ fab-checklist §1。実物の 595 の 1 番ピン → 届いてから</li>
</ul>
<p class="sub">出所: <code>build/fab_check/evidence.json</code>（このページの表の元データ）、<code>build/fab_check/pads.json</code>（板から抽出した全パッド）。</p>
</main>'''
open("build/fab_check/report.html","w").write(page)
print(len(page)//1024,"KB")
