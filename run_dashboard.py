"""Run the Ultimate Aggressor Dashboard as a background process."""
import sys, os, subprocess, time, signal, atexit

os.chdir(r'C:\Users\natar\Downloads\backtesting only 1.0')

# Clean state
for f in ['ultimate_wallet.json', 'ultimate_state.pkl']:
    if os.path.exists(f): os.remove(f)

print("Starting Ultimate Aggressor Dashboard...")
print("Dashboard: http://localhost:8765")
print("Press Enter to stop...\n")

proc = subprocess.Popen(
    [sys.executable, 'ultimate_aggressor.py', '--dashboard'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
)

def cleanup():
    if proc.poll() is None:
        proc.kill()
        proc.wait()
atexit.register(cleanup)

# Wait for it to start
time.sleep(4)

# Verify it's running
import urllib.request, json
try:
    r = urllib.request.urlopen('http://localhost:8765/api/status', timeout=5)
    d = json.loads(r.read())
    s = d['summary']
    print(f"Status: Rs{s['total_value']:.0f} | Trades: {s['trades']} | WR: {s['win_rate']:.1f}%")
    print(f"Agent running: {d['running']} | Regime: {d.get('regime', 'N/A')}")
except Exception as e:
    print(f"API check failed: {e}")

# Keep running until Enter
try:
    input()
except:
    pass

print("Shutting down...")
cleanup()
print("Done.")
