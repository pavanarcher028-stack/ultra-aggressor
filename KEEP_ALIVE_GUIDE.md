# How to run 24/7 without your laptop

## Option 1: Cloud (Recommended) — Free

### Render.com (easiest)
1. Go to https://render.com and sign up (free)
2. Click "New +" → "Web Service"
3. Connect your GitHub or upload the files
4. Render auto-detects `render.yaml` — just click "Apply"
5. Your agent runs 24/7 at `https://your-app.onrender.com`

### Keep it awake (free tier sleeps after 15 min)
- Create free account at https://uptimerobot.com
- Add a monitor that pings your Render URL every 5 minutes
- Keeps it alive 24/7

### Access dashboard
- Open `https://your-app.onrender.com` in any browser
- View from phone, laptop, anywhere

---

## Option 2: Local (laptop closed)

### Step 1: Stop laptop from sleeping when lid closes
1. Open **Control Panel** → **Power Options**
2. Click "Choose what closing the lid does"
3. Set "When I close the lid" → **Do nothing** (for both battery & plugged in)

### Step 2: Run the agent
1. Double-click `run_paper.bat`
2. Choose option 2 (Agent + Dashboard)
3. Open http://localhost:8765 in your browser

### Step 3: Close the lid
- Laptop stays on. Agent keeps running.
- Open http://localhost:8765 from any device on same WiFi (use your laptop's IP)

---

## Option 3: Minimal VPS ($3-5/month)
- Hetzner, DigitalOcean, or Oracle Cloud Free Tier
- SSH in, run `python production_aggressor.py --dashboard`
- Use `screen` or `tmux` to keep it running after disconnect

---

## Quick commands for server deployment
```bash
git clone <your-repo>
cd backtesting-only-1.0
pip install -r requirements.txt
python production_aggressor.py --setup
python production_aggressor.py --dashboard
```
