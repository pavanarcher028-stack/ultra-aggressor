# ============================================================
# TERMUX QUICK SETUP — 2 minutes total
# ============================================================
# REQUIREMENT: Install Termux from F-Droid (NOT Play Store)
#   https://f-droid.org/packages/com.termux/
#
# Then paste each block one at a time:

# --- BLOCK 1: Update (1 min) ---
pkg update -y && pkg upgrade -y && pkg install python git -y

# --- BLOCK 2: Clone (30 sec) ---
cd ~ && git clone https://github.com/pavanarcher028-stack/ultra-aggressor.git && cd ultra-aggressor

# --- BLOCK 3: Install lightweight deps (30 sec, no compilation needed) ---
pip install -r requirements_termux_lite.txt

# --- BLOCK 4: Start dashboard ---
python production_aggressor.py --dashboard

# ============================================================
# ACCESS: Phone browser → http://localhost:8765
# KEEP ALIVE: Settings → Battery → Termux → Background Running
#             Recent apps → Lock Termux (pull-down on card)
# ============================================================
