"""Keeps toxlined running: restarts it whenever it exits. Started at sign-in (a scheduled task or the
Startup shortcut install.ps1 makes), so the service never depends on a terminal or agent session.
Only one supervisor runs at a time; a second one exits straight away."""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = Path(os.environ.get("TOXLINE_HOME", ROOT / "state"))
LOG = STATE / "supervisor.log"
PIDFILE = STATE / "supervisor.pid"
PORT = os.environ.get("TOXLINE_PORT", "8765")
python = Path(sys.executable).with_name("python.exe")   # child gets a real stdout to log into


def log(msg):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def alive(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


try:
    other = int(PIDFILE.read_text().strip())
    if other != os.getpid() and alive(other):
        sys.exit(0)   # already supervised
except (OSError, ValueError):
    pass
STATE.mkdir(parents=True, exist_ok=True)
PIDFILE.write_text(str(os.getpid()))

fails = 0
while True:
    started = time.time()
    log("starting toxlined")
    with open(STATE / "toxline.log", "a", encoding="utf-8") as out:
        code = subprocess.call([str(python), "-X", "utf8", str(ROOT / "toxlined.py"), "--ingress", "desktop",
                                "--port", PORT], cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ran = time.time() - started
    fails = fails + 1 if ran < 30 else 0
    log(f"toxlined exited with code {code} after {ran:.0f}s")
    time.sleep(min(300, 5 * 2 ** min(fails, 6)))   # back off if it keeps failing fast (e.g. port in use)
