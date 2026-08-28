import json,re,sys,math
sys.path.insert(0,"tools")
from PIL import Image,ImageDraw,ImageFont
import matrix, pinmap
P=json.load(open("build/fab_check/pads.json"))
def fp(b,ref): return next(f for f in P[b] if f["ref"]==ref)
def net(b,ref,n):
    f=fp(b,ref); return next(p["net"] for p in f["pads"] if p["n"]==n)
R={}
# ---- 595: TI SCASE93A Table 4-1 (external), expected functional role → nets
TI={1:"QB",2:"QC",3:"QD",4:"QE",5:"QF",6:"QG",7:"QH",8:"GND",9:"QH'",10:"SRCLR",11:"SRCLK",12:"RCLK",13:"OE",14:"SER",15:"QA",16:"VCC"}
def expect595(role,chain_in,cols):
    return {"GND":["GND"],"VCC":["V3V3"],"SRCLR":["V3V3"],"OE":["GND"],"SRCLK":["SPI_SCK"],"RCLK":["CS"],"SER":[chain_in],
            "QA":[cols[0]],"QB":[cols[1]],"QC":[cols[2]],"QD":[cols[3]],"QE":[cols[4]],"QF":[cols[5]],"QG":[cols[6]],"QH":[cols[7]],"QH'":["U1_U2","NC",""],"":["",""]}[role]
rows595=[]
for b,ref,cin,cols in (("left","U1","SPI_MOSI",[f"COL{i}" for i in range(6)]+["",""]),("right","U1","SPI_MOSI",[f"COL{i}" for i in range(8)]),("right","U2","U1_U2",["COL8"]+[""]*7)):
    for n in range(1,17):
        act=net(b,ref,str(n)); exp=expect595(TI[n],cin,cols)
        rows595.append({"board":b,"ref":ref,"pin":n,"ti":TI[n],"expected":"/".join(e for e in exp if e) or "(未使用)","actual":act or "(無し)","ok": act in exp})
R["u595"]=rows595
# ---- XIAO: Seeed official pinout (external) - pad name→position; role expectation from firmware
xf=fp("daughterboard","U_MCU")
seeed={"D0":(-7.62,-7.62),"D1":(-7.62,-5.08),"D2":(-7.62,-2.54),"D3":(-7.62,0),"D4":(-7.62,2.54),"D5":(-7.62,5.08),"D6":(-7.62,7.62),
       "5V":(7.62,-7.62),"GND":(7.62,-5.08),"3V3":(7.62,-2.54),"D10":(7.62,0),"D9":(7.62,2.54),"D8":(7.62,5.08),"D7":(7.62,7.62)}
fw={}  # from overlay/dtsi
rp=matrix.row_pins("left")
for i,p in enumerate(rp): fw[p]=f"ROW{i}(left)"
rpr=matrix.row_pins("right")
for i,p in enumerate(rpr): fw[p]=fw.get(p,"")+f" ROW{i}(right)"
dtsi=open("config/boards/shields/hhkb_split/hhkb_split.dtsi").read()
cs=re.search(r"cs-gpios\s*=\s*<&xiao_d\s+(\d+)",dtsi)[1]
fw[f"D{cs}"]="SPI CS"; fw["D8"]="SPI SCK (board pinctrl P1.13)"; fw["D10"]="SPI MOSI (P1.15)"; fw["D9"]="SPI MISO (P1.14) 未使用"
fw["D0"]="ADC AIN0 電池電圧"
xrows=[]
for name,(ex,ey) in seeed.items():
    pad=next(p for p in xf["pads"] if p["n"]==name)
    # world = c + R(rot) local ; fp on F.Cu rot?
    rot=math.radians(xf["rot"]); lx,ly=pad["x"]-xf["x"],pad["y"]-xf["y"]
    # unrotate
    ux= lx*math.cos(rot)+ly*math.sin(rot); uy=-lx*math.sin(rot)+ly*math.cos(rot)
    xrows.append({"pad":name,"seeed_xy":(ex,ey),"board_xy":(round(ux,2),round(uy,2)),"pos_ok":abs(ux-ex)<0.05 and abs(uy-ey)<0.05,"net":pad["net"],"firmware":fw.get(name,"")})
R["xiao"]=xrows; R["xiao_fp"]={"layer":xf["layer"],"rot":xf["rot"]}
# ---- FFC: J_DB(left/right) vs J_MAIN pad→net, and pin-1 side geometry
ffc=[]
# J_DB は J_MAIN の鏡像（n ↔ 13-n）。2026-08-28 に J_DB の口を奥向きに回したため。
for n in range(1,13):
    ffc.append({"pin":n,"J_MAIN":net("daughterboard","J_MAIN",str(n)),"jdb_pin":13-n,"left_J_DB":net("left","J_DB",str(13-n)),"right_J_DB":net("right","J_DB",str(13-n))})
R["ffc"]=ffc
geo={}
for b,ref in (("left","J_DB"),("right","J_DB"),("daughterboard","J_MAIN")):
    f=fp(b,ref); p1=next(p for p in f["pads"] if p["n"]=="1"); p12=next(p for p in f["pads"] if p["n"]=="12")
    geo[f"{b}/{ref}"]={"layer":f["layer"],"center":(f["x"],f["y"]),"rot":f["rot"],"pad1":(p1["x"],p1["y"]),"pad12":(p12["x"],p12["y"]),"pad1_side":"+X(右)" if p1["x"]>f["x"] else "-X(左)","pads_side_y":("KiCad -Y(奥) → 口は手前向き" if p1["y"]<f["y"] else "KiCad +Y(手前) → 口は奥向き"),"body":f["bbox"]}
R["ffc_geo"]=geo
# ---- D_PWR schottky + divider on db
d=fp("daughterboard","D_PWR"); R["dpwr"]=[{"pad":p["n"],"role":"K(カソード・帯)" if p["n"]=="1" else "A(アノード)","net":p["net"]} for p in d["pads"]]
R["db_others"]=[{"ref":f["ref"],"val":f["val"],"pads":[(p["n"],p["net"]) for p in f["pads"]]} for f in P["daughterboard"] if f["ref"] not in("U_MCU","J_MAIN","D_PWR") and not f["ref"].startswith("H")]
# ---- matrix chain per key
km=open("config/boards/shields/hhkb_split/hhkb_split.keymap").read()
blk=re.search(r"bindings\s*=\s*<(.*?)>;",km,re.S)[1]; blk=re.sub(r"/\*.*?\*/"," ",blk,flags=re.S)
labels=re.findall(r"&(?:kp|mo)\s+(\S+)",blk)
chain=[]
for half,off in (("left",0),("right",matrix.LEFT_KEYS)):
    asg=matrix.assignments(half); rn=matrix.row_nets(half)
    sws=sorted([f for f in P[half] if re.fullmatch(r"SW\d+",f["ref"])],key=lambda f:int(f["ref"][2:]))
    for i,f in enumerate(sws):
        nets=[p["net"] for p in f["pads"] if p["net"]]
        col=[n for n in nets if n.startswith("COL")]; other=[n for n in nets if not n.startswith("COL")]
        dref,rown="",""
        for dd in P[half]:
            if re.fullmatch(r"D\d+",dd["ref"]) and any(p["net"] in other for p in dd["pads"]):
                dref=dd["ref"]; rown=next(p["net"] for p in dd["pads"] if p["net"].startswith("ROW")); kpad=next(p["n"] for p in dd["pads"] if p["net"] in other); rpad=next(p["n"] for p in dd["pads"] if p["net"].startswith("ROW"))
        r_board=rn.index(rown) if rown in rn else -1; c_board=int(col[0][3:]) if col else -1
        r_fw,c_fw=asg[i]
        chain.append({"half":half,"sw":f["ref"],"key":labels[off+i],"col_net":col[0] if col else "","diode":dref,"diode_anode_pad":kpad,"row_net":rown,"row_pin":rp[r_board] if half=="left" and r_board>=0 else (rpr[r_board] if r_board>=0 else ""),"board_rc":(r_board,c_board),"fw_rc":(r_fw,c_fw),"ok":(r_board,c_board)==(r_fw,c_fw) and kpad=="2" and rpad=="1"})
R["chain"]=chain
R["chain_ok"]=all(c["ok"] for c in chain); R["u595_ok"]=all(r["ok"] for r in rows595); R["xiao_ok"]=all(r["pos_ok"] for r in xrows)
json.dump(R,open("build/fab_check/evidence.json","w"),ensure_ascii=False,indent=1,default=str)
print("595 ok",R["u595_ok"],"xiao pos ok",R["xiao_ok"],"chain ok",R["chain_ok"],len(chain))
for r in rows595:
    if not r["ok"]: print("  595 NG",r)
for c in chain:
    if not c["ok"]: print("  chain NG",c)
# ---- annotated drawings
def draw(b,refs,out,scale=40,pad_mm=3):
    fps=[fp(b,r) for r in refs]
    x0=min(f["bbox"][0] for f in fps)-pad_mm; y0=min(f["bbox"][1] for f in fps)-pad_mm; x1=max(f["bbox"][2] for f in fps)+pad_mm; y1=max(f["bbox"][3] for f in fps)+pad_mm
    W,H=int((x1-x0)*scale),int((y1-y0)*scale); im=Image.new("RGB",(W,H),(250,250,245)); d=ImageDraw.Draw(im)
    try: font=ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",15); small=ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",12)
    except: font=small=ImageFont.load_default()
    T=lambda x,y:((x-x0)*scale,(y-y0)*scale)
    for f in fps:
        a,bb,c,dd=f["bbox"]; d.rectangle([T(a,bb),T(c,dd)],outline=(120,120,120),width=2)
        d.text(T(a,bb-2.5),f'{f["ref"]} ({f["val"]}) 面={f["layer"]} 回転={f["rot"]:.0f}°',fill=(0,0,0),font=font)
        for p in f["pads"]:
            w,h=p["sx"],p["sy"]
            if p["rot"]%180==90: w,h=h,w
            col=(255,200,60) if p["layer"]=="PTH" else ((90,160,255) if p["layer"]=="B.Cu" else (255,120,120))
            d.rectangle([T(p["x"]-w/2,p["y"]-h/2),T(p["x"]+w/2,p["y"]+h/2)],fill=col,outline=(0,0,0))
            d.text(T(p["x"]-w/2,p["y"]-h/2),p["n"],fill=(0,0,0),font=small)
            if p["net"]:
                if h>w*1.5 and w<1.0:   # 縦長の細いパッド（90°回転の TSSOP / FFC）→ 交互に上下へ逃がす
                    k=int(round(p["x"]/0.65))%3
                    ty=p["y"]-h/2-0.6-0.5*k if p["y"]<f["y"] else p["y"]+h/2+0.1+0.5*k
                    d.text(T(p["x"]-0.3,ty),p["net"],fill=(150,0,0),font=small)
                else:
                    d.text(T(p["x"]+w/2+0.1,p["y"]-0.2),p["net"],fill=(150,0,0),font=small)
    d.text((5,H-40),"座標は KiCad（上が奥・Y 下向き）。表から見た図（裏面部品も表から透視）。青=裏面パッド 赤=表面パッド 黄=スルーホール",fill=(0,0,0),font=small)
    d.text((5,H-22),f"1mm = {scale}px",fill=(0,0,0),font=small)
    im.save(out)
draw("left",["U1","C_U1"],"build/fab_check/left_U1_nets.png")
draw("right",["U1","U2","C_U1","C_U2"],"build/fab_check/right_U1_U2_nets.png")
draw("daughterboard",["U_MCU","J_MAIN","D_PWR"],"build/fab_check/db_nets.png",scale=30)
draw("left",["J_DB"],"build/fab_check/left_J_DB_nets.png",scale=50)
draw("right",["J_DB"],"build/fab_check/right_J_DB_nets.png",scale=50)
print("drawn")
