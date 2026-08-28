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
    tf+=f'<tr><td class="n">{r["pin"]}</td><td>{esc(r["left_J_DB"])}</td><td>{esc(r["right_J_DB"])}</td><td>{esc(r["J_MAIN"])}</td><td>{OK if same else NG}</td></tr>'
tc=""
for c in R["chain"]:
    tc+=f'<tr><td>{c["half"]}</td><td>{c["sw"]}</td><td><b>{esc(c["key"])}</b></td><td>{esc(c["col_net"])}</td><td>{c["diode"]}</td><td>{esc(c["row_net"])} ({c["row_pin"]})</td><td class="n">RC({c["board_rc"][0]},{c["board_rc"][1]})</td><td class="n">RC({c["fw_rc"][0]},{c["fw_rc"][1]})</td><td>{OK if c["ok"] else NG}</td></tr>'
g=R["ffc_geo"]
def gr(k):
    v=g[k]; return f'<tr><td>{k}</td><td>{v["layer"]}</td><td class="n">{v["rot"]:.0f}°</td><td>{v["pad1_side"]}</td><td>{v["pads_side_y"]} → 口は手前向き</td></tr>'
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
<div class="card"><b>FFC ケーブル</b><div class="big">{NG} 要判断</div>A タイプでは接点面が合わない可能性（板は無傷）</div>
</div>

<div class="alert"><b>起きたら見るもの（1 つだけ判断が要る）</b><br>
FFC は、ピン対応（1→1、ネット並びは 3 コネクタで完全一致）は正しいのですが、<b>ケーブルの経路に「厚み方向の U ターン」が 1 回</b>あり、そこで接点面が裏返ります。両端のコネクタは<b>下接点</b>で両方とも基板の裏に付くので、<b>A タイプ（同面接点）では両端を同時に満たせず、B タイプ（両端で接点面が逆）が要る</b>と読めます。これは open-gaps #19（2026-08-16「A タイプで決着」）の見落としです。下の §1 の図と、紙のリボンで 1 分で確かめられます。</div>

<div class="todo"><b>あなたがやること（順番どおり・合計 30 分）</b>
<ol>
<li><b>紙のリボンで §1 を再現する</b>（片面に線を引き、図の経路をなぞる）。私の読みが合っていれば、床で線が下を向きます</li>
<li>合っていたら <b>B タイプ 80mm を買う</b>か、<b>J_DB を 180° 回して U ターンを無くす</b>かを決める（後者は板の変更・発注前限定）。A タイプを既に買っていたら B を買い足す</li>
<li><b>1:1 印刷</b>: <code>build/fab_check/daughterboard_1to1_top_view.pdf</code> を「実際のサイズ」で印刷し、手元の XIAO を載せる（§3）。印刷の正しさは取付穴の間隔 <b>16.0mm</b> を定規で見る</li>
<li>595 が届いたら、シルクの 1 番ピン印（§2 の図の左下・右は上）と実物の丸印を見比べる</li>
</ol></div>

<h2>1. FFC — ピン対応は正しい。接点面の向きに問題</h2>
<h3>1a. ピン対応（3 コネクタでネットの並びが同じ）</h3>
<div class="tbl"><table><tr><th>ピン</th><th>左 J_DB</th><th>右 J_DB</th><th>子基板 J_MAIN</th><th>判定</th></tr>{tf}</table></div>
<h3>1b. 幾何（板の実体から）</h3>
<div class="tbl"><table><tr><th>コネクタ</th><th>面</th><th>回転</th><th>ピン 1 の側</th><th>パッドの側</th></tr>{gr("left/J_DB")}{gr("right/J_DB")}{gr("daughterboard/J_MAIN")}</table></div>
<p>3 つとも <b>裏面（B.Cu）・回転 180°・ピン 1 が +X 側・パッドが奥側＝口が手前向き</b>。これは組立モデル <code>gen_assembly.py</code> の記述「J_DB（口は手前向き）から下りて床の上を這い、J_MAIN（口は手前向き）へ入る」と一致します。</p>
<h3>1c. 接点面を追う（横から見た図・手前が左）</h3>
<figure>
<svg viewBox="0 0 820 330" width="100%" role="img" aria-label="FFC 経路の側面図">
<defs><marker id="ar" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 z" fill="var(--acc)"/></marker></defs>
<text x="20" y="20" fill="var(--mute)">横から見た図。左＝手前（キー側）、右＝奥（コブ・電池側）。縮尺なし。赤い短線＝導体（接点）が出ている面。</text>
<line x1="40" y1="110" x2="440" y2="80" stroke="var(--ink)" stroke-width="5"/><text x="40" y="60">本体基板（7.3° 傾き・裏が下）</text>
<rect x="320" y="91" width="70" height="16" fill="var(--code)" stroke="var(--ink)"/><text x="400" y="105">J_DB（裏面・下接点・口は手前）</text>
<line x1="540" y1="200" x2="790" y2="200" stroke="var(--ink)" stroke-width="5"/><text x="600" y="190">子基板（水平・裏が下）</text>
<rect x="545" y="203" width="60" height="16" fill="var(--code)" stroke="var(--ink)"/><text x="612" y="217">J_MAIN（裏面・下接点・口は手前）</text>
<line x1="30" y1="285" x2="800" y2="285" stroke="var(--mute)" stroke-width="2" stroke-dasharray="6 4"/><text x="35" y="305" fill="var(--mute)">床</text>
<path d="M320,101 L270,101 Q250,101 250,121 L250,250 Q250,268 268,268 L500,268 Q520,268 520,250 L520,225 Q520,211 534,211 L542,211" fill="none" stroke="var(--acc)" stroke-width="4" marker-end="url(#ar)"/>
<g stroke="var(--ng)" stroke-width="3">
<line x1="280" y1="96" x2="310" y2="96"/>
<line x1="245" y1="160" x2="245" y2="190"/>
<line x1="350" y1="273" x2="400" y2="273"/>
<line x1="525" y1="228" x2="525" y2="242"/>
<line x1="534" y1="216" x2="542" y2="216"/>
</g>
<text x="150" y="128" fill="var(--ng)">① J_DB では上向き（基板側）✓</text>
<text x="120" y="180" fill="var(--ng)">② 折り下げ：手前を向く</text>
<text x="290" y="300" fill="var(--ng)">③ 床で下向き（U ターンで裏返った）</text>
<text x="330" y="245" fill="var(--ng)">④ 上がる S 字では向きは戻らない</text>
<text x="545" y="245" fill="var(--ng)">⑤ 下向きのまま J_MAIN へ ✗</text>
<text x="545" y="262" fill="var(--ng)">（下接点なので上向きが要る）</text>
</svg>
<figcaption>位置関係は STEP の寸法で確認済み（J_DB z −3.6〜−1.6・J_MAIN z −2.1〜−0.1 で両方とも板の下、アクチュエータ片が両方とも手前側）。J_DB で上を向いていた導体は、手前→下→奥の U ターンで下向きになり、床→上→奥の S 字では戻らない。J_MAIN は基板の裏に付いた下接点なので上向きが必要。</figcaption>
</figure>
<p>根拠: FH12-xxS-0.5SH は下接点（DigiKey 品目「Bottom contacts」。上接点は FH12<b>A</b>）。180° ひねりは面と一緒にピン 1↔12 も反転するので、1a の「ネット並び一致」と矛盾し代用になりません。<b>B タイプ（両端で接点面が逆・導体はまっすぐ）ならピン 1→1 のまま両端が合います。</b></p>
<div class="note">私が決めていないこと: A/B どちらを買うか、J_DB を回すか。記録は open-gaps #19 に「🔴 再開」として書きました。fab-checklist §7 の視点 C（1:1 印刷に実物を渡す）で確かめてから決めてください。</div>

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
