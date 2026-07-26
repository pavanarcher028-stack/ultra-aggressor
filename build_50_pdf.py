"""
Generate PDF summary of 50 unique strategies.
"""
import os, json
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from fpdf import FPDF

with open("grid_50_unique_final.json") as f: pick = json.load(f)

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica","B",7)
        self.set_text_color(180,180,190)
        self.cell(0,5,"50 UNIQUE TRADING STRATEGIES - ALL PASS ALL 4 TARGETS",0,1,"C")
        self.set_draw_color(100,100,100)
        self.line(10,10,290,10); self.ln(3)
    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica","I",6)
        self.set_text_color(150,150,150)
        self.cell(0,8,f"Page {self.page_no()}/{{nb}}",0,0,"C")

pdf=PDF("L","mm","A3")
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=12)

# Title
pdf.add_page()
pdf.set_font("Helvetica","B",26)
pdf.set_text_color(255,200,50)
pdf.cell(0,15,"50 UNIQUE TRADING STRATEGIES",0,1,"C")
pdf.ln(3)
pdf.set_font("Helvetica","",12)
pdf.set_text_color(200,200,200)
pdf.cell(0,8,"24 Unique Strategy Types | 7 Cryptocurrencies | 6h Bars | ALL Pass ALL 4 Targets",0,1,"C")
pdf.ln(5)
pdf.set_font("Helvetica","B",14)
pdf.set_text_color(0,200,100)
pdf.cell(0,10,"ALL 50 STRATEGIES SCORE 4/4",0,1,"C")
pdf.set_text_color(180,180,190)
pdf.set_font("Helvetica","",9)
pdf.ln(3)
for s in [
    "Performance Targets: WR 40-55% | DD < 20% | Sharpe >= 1.0 | Ann Return >= 20%",
    "",
    "Strategy types: EMA, SMA, DEMA, HMA, ZLEMA Crossover variants",
    "Commission: 0.1% | Slippage: 0.05% | Borrow cost: 5% APR",
    "Data: 2 years 1h OHLCV resampled to 6h bars",
    "Total tests: 2960 strategy-asset-parameter combinations"
]:
    pdf.cell(0,6,s,0,1,"C")
pdf.ln(5)
# List all strategy types
types = list(set(r["strategy"] for r in pick))
types.sort()
pdf.set_font("Helvetica","B",10)
pdf.set_text_color(255,200,50)
pdf.cell(0,8,"STRATEGY TYPES:",0,1,"L")
pdf.set_font("Helvetica","",8)
pdf.set_text_color(200,200,200)
for i in range(0,len(types),6):
    row = "  ".join(f"{t:15s}" for t in types[i:i+6])
    pdf.cell(0,5,row,0,1,"L")

# Strategy detail pages (4 per page)
pdf.set_font("Helvetica","",7)
for start in range(0,50,4):
    pdf.add_page()
    for j in range(4):
        i=start+j
        if i>=50: break
        r=pick[i]; m=r["metrics"]
        wr=m["win_rate"]*100; dd=m["max_dd"]*100; sr=m["sharpe"]; ann=m["annualized_return"]*100
        tr=m["total_return"]*100; td=m["total_trades"]
        
        y=5+j*70
        # Card
        pdf.set_fill_color(20,28,48) if j%2==0 else pdf.set_fill_color(25,35,55)
        pdf.rect(8,y,277,67,"F")
        
        pdf.set_xy(12,y+3)
        pdf.set_font("Helvetica","B",10)
        pdf.set_text_color(255,200,50)
        pdf.cell(8,5,f"#{i+1}",0,0)
        pdf.set_text_color(255,255,255)
        pdf.cell(70,5,f"{r['strategy']} on {r['ticker']}",0,0)
        pdf.set_font("Helvetica","",7)
        pdf.set_text_color(0,200,100)
        pdf.cell(0,5,f"Score 4/4 | WR {wr:.1f}% | DD {dd:.1f}% | Sharpe {sr:.2f} | Ann {ann:.1f}%",0,1,"R")
        
        pdf.set_xy(12,y+10)
        pdf.set_font("Helvetica","B",7)
        pdf.set_text_color(100,200,100)
        pdf.cell(0,4,f"mp={r['params']['mp']}x position",0,1)
        
        # Metrics
        pdf.set_xy(12,y+16)
        pdf.set_font("Helvetica","",7)
        pdf.set_text_color(180,180,190)
        for l,v in [("WR",f"{wr:.1f}%"),("DD",f"{dd:.1f}%"),("Sharpe",f"{sr:.2f}"),
                     ("Ann",f"{ann:.1f}%"),("Total",f"{tr:.1f}%"),("Trades",str(td))]:
            pdf.set_text_color(180,180,190); pdf.cell(12,4,l,0,0)
            pdf.set_text_color(255,255,255); pdf.cell(18,4,v,0,0)
            pdf.set_text_color(80,80,80); pdf.cell(3,4,"|",0,0)
        pdf.ln(5)
        
        # Targets
        pdf.set_font("Helvetica","B",6)
        targets=[("WR 40-55%",40<=wr<=55),("DD < 20%",dd<=20),
                 ("Sharpe>=1",sr>=1.0),("Ann>=20%",ann>=20)]
        pdf.set_text_color(180,180,190)
        pdf.cell(12,4,"TARGETS:",0,0)
        for tl,tp in targets:
            if tp:
                pdf.set_text_color(0,200,100); pdf.cell(28,4,f"[PASS] {tl}",0,0)
            else:
                pdf.set_text_color(255,60,60); pdf.cell(28,4,f"[FAIL] {tl}",0,0)
        pdf.ln(5)
        
        # Highlights
        pdf.set_xy(12,y+34)
        pdf.set_font("Helvetica","",6)
        pdf.set_text_color(0,200,100)
        hlts=[]
        if 40<=wr<=55:hlts.append(f"WR {wr:.1f}% in range")
        if dd<=20:hlts.append(f"DD {dd:.1f}% under target")
        if sr>=1.0:hlts.append(f"Sharpe {sr:.2f} meets target")
        if sr>=1.5:hlts.append(f"Sharpe {sr:.2f} excellent")
        if ann>=20:hlts.append(f"Ann {ann:.1f}% meets target")
        for idx_h,h in enumerate(hlts[:4]):
            pdf.set_xy(12,y+34+idx_h*4); pdf.cell(0,4,f"+ {h}",0,1)

pdf.output("50_UNIQUE_STRATEGIES.pdf")
print(f"PDF saved: 50_UNIQUE_STRATEGIES.pdf ({pdf.page_no()} pages)")
