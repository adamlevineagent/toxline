"""Ingress: getting a guest's message into their agent thread.

An ingress adapter does four things:
  create_thread(contact) -> thread_id     start a dedicated thread with the guide brief
  deliver(contact, message) -> {state, detail}
  open_thread(thread_id)                  show the thread to the owner
  list_threads(q)                         candidate threads for binding

'codex' drives Codex threads (see codex_ingress.py). 'fake' is a stand-in agent
that answers through the same tox-send API, so everything else can be tested
without spending model turns.
"""
import json
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from . import db as dbmod

DEFAULT_PERSONA = (Path(__file__).resolve().parent / "persona_default.md")


class BaseIngress:
    name = "base"

    def __init__(self, journal, port):
        self.j = journal
        self.port = port
        self.on_activity = None

    def read_thread(self, thread_id, limit_turns=30):
        return []

    def submit(self, thread_id, text, **kw):
        return {"state": "delivered_to_thread", "detail": "no-op"}

    def busy(self, thread_id):
        return False

    def persona_path(self):
        return dbmod.HOME / "persona.md"

    def persona_text(self):
        p = self.persona_path()
        return p.read_text(encoding="utf-8") if p.exists() else DEFAULT_PERSONA.read_text(encoding="utf-8")

    def set_persona_text(self, text):
        self.persona_path().write_text(text, encoding="utf-8")

    def describe(self):
        return self.name

    def connection_brief(self, contact, others=()):
        """One-time note posted into an existing thread when a guest is bound to it."""
        from . import config
        cfg = config.load()
        owner = cfg["owner"]
        send = str(Path(__file__).resolve().parent.parent / "bin" / "tox-send.ps1")
        about = contact.get("notes") or ""
        name = contact["name"]
        lines = [
            f"[Toxline] This thread is now connected to {name} over Tox.",
            f"- Their messages arrive here as blocks starting with `[Tox message from {name}]`. "
            f"They can't see this thread; only what you send reaches them.",
            f'- To message them, run in PowerShell: `& "{send}" "your message"`. For anything long, '
            f"multi-line, or containing quotes, write it to a UTF-8 file and use `--file path`. "
            f"`--who` shows the recent chat. Plain conversational text reads best in their chat client.",
            f"- Answer them by default. {owner}'s messages in this thread are private steering; "
            f'"tell {name} X" means send it, "draft first" means don\'t send yet.',
        ]
        if about:
            lines.append(f"- About {name}: {about}")
        if others:
            everyone = ", ".join([*others, name])
            lines.append(
                f"- This thread is shared: it talks to {everyone}. Each message block says who wrote it, "
                f"and each person only sees what you send to them. Add `--to {name}` (or `--to all`, "
                f"or several names separated by commas) to every tox-send. Other guests in this thread "
                f"don't see {name}'s messages unless you pass them on.")
        if cfg["library_map"]:
            topic = f"about {cfg['topic']} " if cfg["topic"] else ""
            lines.append(f"- To answer questions {topic}start from the reference map: `{cfg['library_map']}`.")
        lines.append(f"Acknowledge in one short line here; don't message them until they write or {owner} asks.")
        return "\n".join(lines)

    def list_threads(self, q=""):
        return []

    def open_thread(self, thread_id):
        return {"ok": False, "note": "this ingress has no thread UI"}


class FakeIngress(BaseIngress):
    """Pretend agent: replies via the real /api/send path after a short think."""
    name = "fake (test agent, no model)"

    def __init__(self, journal, port):
        super().__init__(journal, port)
        self.turns = {}      # thread_id -> [turn dicts], an in-memory stand-in transcript
        self._busy = set()

    def create_thread(self, contact):
        return str(uuid.uuid4())

    def deliver(self, contact, message):
        return self.submit(contact["thread_id"], f"[Tox message from {contact['name']}]\n{message['body']}")

    def submit(self, tid, text, **kw):
        turn = {"id": uuid.uuid4().hex[:8], "status": "inProgress",
                "items": [{"type": "userMessage", "text": text}]}
        self.turns.setdefault(tid, []).append(turn)
        self._busy.add(tid)
        self._emit(tid, "turn_started", {})
        guest = text.startswith("[Tox message from ")
        body = text.split("\n", 1)[1] if guest and "\n" in text else text

        def run():
            time.sleep(1.0)
            if guest:
                reply = f"(fake agent) You said: {body[:200]}"
                turn["items"].append({"type": "commandExecution", "command": f'tox-send "{reply}"',
                                      "status": "completed", "exitCode": 0, "output": "To guest: DELIVERED"})
                who = text[len("[Tox message from "):text.index("]")]
                data = json.dumps({"thread_id": tid, "origin": "fake-agent", "body": reply, "to": who}).encode()
                req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/send", data=data,
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).read()
                turn["items"].append({"type": "agentMessage", "text": "Replied to the guest."})
            else:
                turn["items"].append({"type": "agentMessage", "text": f"(fake agent) Noted: {body[:200]}"})
            turn["status"] = "completed"
            self._busy.discard(tid)
            self._emit(tid, "turn_completed", {})

        threading.Thread(target=run, daemon=True).start()
        return {"state": "delivered_to_thread", "detail": "fake agent"}

    def _emit(self, tid, kind, data):
        if self.on_activity:
            self.on_activity(tid, kind, data)

    def read_thread(self, thread_id, limit_turns=30):
        return self.turns.get(thread_id, [])[-limit_turns:]

    def busy(self, thread_id):
        return thread_id in self._busy


def make_ingress(kind, journal, port):
    if kind == "fake":
        return FakeIngress(journal, port)
    if kind == "desktop":
        from .pipe_ingress import DesktopIngress
        return DesktopIngress(journal, port)
    if kind == "codex":
        from .codex_ingress import CodexIngress
        return CodexIngress(journal, port)
    raise SystemExit(f"unknown ingress {kind!r}")
