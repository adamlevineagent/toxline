"""Print the latest turns of a Codex thread via Desktop (debugging aid)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from toxline.pipe_ingress import DesktopIngress
from toxline import db

j = db.Journal()
ing = DesktopIngress(j, 8765)
r = ing._tool("read_thread", {"threadId": sys.argv[1], "turnLimit": int(sys.argv[2]) if len(sys.argv) > 2 else 1,
                              "includeOutputs": False}, j.get("home_thread"))
print(json.dumps(r, indent=1, ensure_ascii=False)[:int(sys.argv[3]) if len(sys.argv) > 3 else 4000])
