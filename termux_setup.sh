# ============================================================
# TERMUX SETUP — 3 blocks, 2 minutes total
# ============================================================
# Install Termux from F-Droid: https://f-droid.org/packages/com.termux/
# Then paste each block:

# --- BLOCK 1: Update (1 min) ---
pkg update -y && pkg upgrade -y && pkg install python git -y

# --- BLOCK 2: Clone + install (30 sec) ---
cd ~ && git clone https://github.com/pavanarcher028-stack/ultra-aggressor.git && cd ultra-aggressor && pip install -r requirements_termux_lite.txt

# --- BLOCK 3: Run ---
python production_aggressor.py --dashboard
