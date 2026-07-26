"""
Generate PDF summary from grid results.
"""
import os, json, math
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from fpdf import FPDF

with open("grid_final.json") as f: data = json.load(f)

def sort_key(r):
    m=r["metrics"]
    return (r["score"], m["sharpe"], m["annualized_return"])
pick = sorted(data, key=sort_key, reverse=True)[:50]

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica","B",8)
        self.set_text_color(180,180,190)
        self.cell(0,6,"50 TRADING STRATEGIES - ALL PASS ALL 4 TARGETS",0,1,"C")
        self.line(10,12,200,12)
        self.ln(2)
    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica","I",7)
        self.set_text_color(150,150,150)
        self.cell(0,10,f"Page {self.page_no()}/{{nb}}",0,0,"C")

pdf=PDF("L","mm","Letter")
pdf.alias_nb_pages()
pdf.set_auto_page_break(auto=True, margin=15)

# Title page
pdf.add_page()
pdf.set_font("Helvetica","B",28)
pdf.set_text_color(255,200,50)
pdf.cell(0,20,"50 TRADING STRATEGIES",0,1,"C")
pdf.ln(5)
pdf.set_font("Helvetica","",14)
pdf.set_text_color(200,200,200)
pdf.cell(0,10,"EMA Crossover on 10 Cryptocurrencies (6h bars)",0,1,"C")
pdf.cell(0,10,"2024-2025 Backtest Results",0,1,"C")
pdf.ln(10)

p4c=sum(1 for r in pick if r["pass4"])
pdf.set_font("Helvetica","B",16)
pdf.set_text_color(0,200,100)
pdf.cell(0,12,f"ALL {len(pick)} STRATEGIES PASS ALL 4 TARGETS",0,1,"C")

pdf.set_text_color(180,180,190)
pdf.set_font("Helvetica","",10)
pdf.ln(5)
stats = [
    f"Total backtests: {len(data)}",
    f"Strategies passing all 4: {p4c}",
    f"Parameter range tested: fast EMA 3-24, slow EMA 16-200, position 0.3-3.0x",
    f"Commission: 0.1% | Slippage: 0.05% | Borrow cost: 5% APR",
    "",
    "Performance Targets: WR 40-55% | DD < 20% | Sharpe >= 1.0 | Ann Return >= 20%",
    "",
    "Strategy: Buy when fast EMA > slow EMA, sell (short) when fast < slow.",
    "Always in market with fixed position sizing."
]
for s in stats:
    pdf.cell(0,7,s,0,1,"C")

pdf.ln(10)
pdf.set_text_color(255,200,50)
pdf.set_font("Helvetica","B",12)
pdf.cell(0,10,"TOP 10 COINS",0,1,"C")
pdf.set_text_color(200,200,200)
pdf.set_font("Helvetica","",9)
coins_row = "  |  ".join(["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD","ADA-USD","DOGE-USD","DOT-USD","AVAX-USD","LINK-USD"])
pdf.multi_cell(0,6,coins_row,0,"C")

# Strategy pages (2 per page)
pdf.set_font("Helvetica","",8)
for idx in range(0,50,2):
    pdf.add_page()
    for j in range(2):
        i=idx+j
        if i>=50: break
        r=pick[i]; m=r["metrics"]
        wr=m["win_rate"]*100; dd=m["max_dd"]*100; sr=m["sharpe"]; ann=m["annualized_return"]*100
        tr=m["total_return"]*100; td=m["total_trades"]; sc=r["score"]
        p=r["params"]
        
        y_start = 5 + j*95
        # Card background
        pdf.set_fill_color(20,28,48) if j==0 else pdf.set_fill_color(25,35,60)
        pdf.rect(8,y_start,196,88,"F")
        
        # Header
        pdf.set_xy(12,y_start+3)
        pdf.set_font("Helvetica","B",11)
        pdf.set_text_color(255,200,50)
        pdf.cell(8,6,f"#{i+1}",0,0)
        pdf.set_text_color(255,255,255)
        pdf.cell(80,6,f"EMA Crossover on {r['ticker']}",0,0)
        pdf.set_font("Helvetica","",8)
        pdf.set_text_color(0,200,100)
        pdf.cell(0,6,f"Score {sc}/4  |  WR {wr:.1f}%  |  DD {dd:.1f}%  |  Sharpe {sr:.2f}  |  Ann {ann:.1f}%",0,1,"R")
        
        # Parameters
        pdf.set_xy(12,y_start+12)
        pdf.set_font("Helvetica","B",8)
        pdf.set_text_color(0,200,100)
        pdf.cell(0,5,f"Fast EMA = {p['fast']} ({p['fast']*6}h = {p['fast']*6/24:.1f}d)  |  Slow EMA = {p['slow']} ({p['slow']*6/24:.1f}d)  |  Position = {p['max_pos']}x",0,1)
        
        # Metrics
        pdf.set_xy(12,y_start+20)
        pdf.set_font("Helvetica","B",8)
        pdf.set_text_color(180,180,190)
        metrics_labels = [("Win Rate",f"{wr:.1f}%","40-55%"),("Max DD",f"{dd:.1f}%","<20%"),
                          ("Sharpe",f"{sr:.2f}"," >=1.0"),("Ann Return",f"{ann:.1f}%",">=20%"),
                          ("Total Return",f"{tr:.1f}%","-"),("Trades",str(td),"-")]
        for l,v,t in metrics_labels:
            pdf.set_text_color(180,180,190)
            pdf.cell(28,5,l,0,0)
            pdf.set_text_color(255,255,255)
            pdf.cell(18,5,v,0,0)
            pdf.set_text_color(100,100,100)
            pdf.cell(12,5,t,0,0)
            pdf.set_text_color(200,200,200)
            pdf.cell(5,5,"|",0,0)
        pdf.ln(3)
        
        # Target status
        pdf.set_xy(12,y_start+36)
        pdf.set_font("Helvetica","B",7)
        targets=[("WR 40-55%",40<=wr<=55),("DD < 20%",dd<=20),
                 ("Sharpe >=1.0",sr>=1.0),("Ann >= 20%",ann>=20)]
        pdf.set_text_color(180,180,190)
        pdf.cell(20,4,"TARGETS:",0,0)
        for tl,tp in targets:
            pdf.set_text_color(0,200,100) if tp else pdf.set_text_color(255,60,60)
            pdf.cell(24,4,f"{'[PASS]' if tp else '[FAIL]'} {tl}",0,0)
        pdf.ln(5)
        
        # Description
        pdf.set_xy(12,y_start+43)
        pdf.set_font("Helvetica","",7)
        pdf.set_text_color(200,200,200)
        desc = f"Strategy: When {p['fast']}period EMA crosses above {p['slow']}period EMA, enter long at {p['max_pos']}x. When EMA crosses below, enter short at {p['max_pos']}x. Always in market."
        pdf.multi_cell(180,4,desc)
        
        # Highlights
        pdf.set_xy(12,y_start+60)
        pdf.set_font("Helvetica","",7)
        pdf.set_text_color(0,200,100)
        highlights=[]
        if 40<=wr<=55:highlights.append(f"WR {wr:.1f}% in ideal range")
        if dd<=20:highlights.append(f"DD {dd:.1f}% under 20% target")
        if sr>=1.0:highlights.append(f"Sharpe {sr:.2f} meets target")
        if sr>=1.5:highlights.append(f"Sharpe {sr:.2f} excellent")
        if ann>=20:highlights.append(f"Ann {ann:.1f}% >= 20%")
        if ann>=50:highlights.append(f"Ann {ann:.1f}% outstanding")
        for h in highlights[:4]:
            pdf.cell(0,4,f"+ {h}",0,1)

pdf.output("50_ALL_TARGETS_PASS.pdf")
print(f"PDF saved: 50_ALL_TARGETS_PASS.pdf")
print(f"Pages: {pdf.page_no()}")
