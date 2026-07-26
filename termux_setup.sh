# ============================================================
# TERMUX SETUP — Run these commands one block at a time
# ============================================================
# REQUIREMENT: Install Termux from F-Droid (NOT Play Store):
#   https://f-droid.org/packages/com.termux/
#
# Then paste each block into Termux:

# --- BLOCK 1: Update (2 min) ---
pkg update -y && pkg upgrade -y && pkg install python git openssl -y

# --- BLOCK 2: Clone repo (30 sec) ---
cd ~ && git clone https://github.com/pavanarcher028-stack/ultra-aggressor.git && cd ultra-aggressor

# --- BLOCK 3: Install deps (2 min) ---
pip install --upgrade pip
pip install -r requirements_termux.txt

# Try solders+solana for real-trade support (optional, 5 min Rust compile):
pip install solders solana 2>/dev/null && echo "solders OK" || echo "Using paper-only mode"

# --- BLOCK 4: Start (press Ctrl+C to stop) ---
python production_aggressor.py --dashboard

# ============================================================
# ACCESS
# ============================================================
# Phone browser:  http://localhost:8765
# Laptop browser: http://<phone-ip>:8765  (find IP: ifconfig wlan0 | grep inet)
#
# KEEP RUNNING WITH SCREEN OFF:
#   Settings → Battery → App Management → Termux
#     → Manual management → Allow Background Running
#   Recent apps → Lock Termux (pull-down on app card)
#
# KEEP RUNNING AFTER REBOOT:
#   Install Termux:Boot from F-Droid
#   Create ~/.termux/boot/start.sh with:
#     cd ~/ultra-aggressor && python production_aggressor.py --dashboard &
