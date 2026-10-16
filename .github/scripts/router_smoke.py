"""CI smoke test of the frozen Revit MCP Router (Windows runner, no licence, no Revit).

    python router_smoke.py "<dist>/Revit MCP Router" <screenshot.png>

1. RevitMcpBridge.exe --check            -> prints bridge / licence / tools lines
2. Revit MCP Router Setup.exe --selftest -> prints selftest_result.txt
3. Starts the Setup window and waits for ANY top-level window of that process (the main window or,
   on an unlicensed runner, the activation dialog; a crash shows PyInstaller's error box). Fails if
   the process exits or shows nothing within 60 s. A screenshot is saved either way.
"""
import ctypes
import ctypes.wintypes as w
import os
import subprocess
import sys
import time

app, shot = sys.argv[1], sys.argv[2]
setup = os.path.join(app, "Revit MCP Router Setup.exe")
bridge = os.path.join(app, "RevitMcpBridge.exe")
os.environ.setdefault("REVIT_MCP_EXTENSION_DIR",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts",
                                   "RevitMcpRouter", "extension_snapshot"))
failed = []

print("== RevitMcpBridge.exe --check", flush=True)
r = subprocess.run([bridge, "--check"], capture_output=True, text=True, timeout=180)
print(r.stdout[-4000:], r.stderr[-4000:], "exit", r.returncode, flush=True)

print("== Revit MCP Router Setup.exe --selftest", flush=True)
res = os.path.join(app, "selftest_result.txt")
if os.path.exists(res):
    os.remove(res)
subprocess.run([setup, "--selftest"], timeout=180)
for _ in range(120):
    if os.path.exists(res):
        break
    time.sleep(0.5)
print(open(res, encoding="utf-8").read() if os.path.exists(res) else "(no selftest_result.txt)", flush=True)

print("== Setup window", flush=True)
p = subprocess.Popen([setup])
u = ctypes.windll.user32
titles = []


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def cb(h, _l):
    pid = w.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if u.IsWindowVisible(h) and pid.value == p.pid:
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        titles.append(b.value)
    return True


deadline = time.time() + 60
while not titles and time.time() < deadline and p.poll() is None:
    time.sleep(0.5)
    u.EnumWindows(cb, 0)
time.sleep(3)                               # let it paint before the screenshot
try:
    from PIL import ImageGrab
    ImageGrab.grab().save(shot)
    print("screenshot:", shot)
except Exception as e:                      # noqa: BLE001
    print("no screenshot:", e)
if titles:
    print("ok    window(s):", titles)
else:
    failed.append("no window (process %s)" % ("exited with %s" % p.returncode if p.poll() is not None else "still running"))
subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
if failed:
    sys.exit("FAILED: " + "; ".join(failed))
print("smoke OK")
