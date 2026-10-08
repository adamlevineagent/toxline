"""Codex ingress: guest threads are ordinary Codex threads driven by toxline's own app-server.

How delivery works
- Toxline runs one `codex app-server` (the same binary Codex Desktop bundles). Threads it
  creates are normal Codex threads: they show up in Codex Desktop, open there, and you can
  type in them.
- A guest message becomes a user turn in that thread right away: `turn/start` if the agent
  is idle, `turn/steer` into the running turn if it's busy (no queue, no waiting for idle).
- Codex allows one writer per thread. After each turn toxline unsubscribes, and the runtime
  releases the thread ~60s later, so Desktop can open it. If Desktop has the thread open,
  toxline can't write to it; the message waits (and is retried) until Desktop lets go, and
  the viewer says so.
"""
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import db as dbmod
from .codex_appserver import AppServer, RpcError
from .ingress import BaseIngress

ROOT = Path(__file__).resolve().parent.parent
TOX_SEND = str(ROOT / "bin" / "tox-send.ps1")
GUEST_ROOT = Path(os.environ.get("TOXLINE_GUEST_ROOT", ROOT / "guests"))
LOCKED = "already has an active writer"
# Guest threads are driven by people outside this machine, so they run sandboxed:
# read anywhere, write only inside their own guest folder, network on so tox-send can
# reach the local toxline service. Approvals are off and any escalation is declined.
SANDBOX_CONFIG = {"sandbox_workspace_write": {"network_access": True}}


def log(*a):
    print(time.strftime("%H:%M:%S"), "[codex]", *a, flush=True)


class CodexIngress(BaseIngress):
    name = "codex"

    def __init__(self, journal, port):
        super().__init__(journal, port)
        self.server = None
        self._start_lock = threading.Lock()
        self.active_turn = {}       # thread_id -> turn_id while a turn runs in OUR server
        self.turn_done = {}         # thread_id -> Event
        self.on_activity = None     # fn(thread_id, kind, data) set by the service
        self.model = os.environ.get("TOXLINE_MODEL") or None
        self.effort = os.environ.get("TOXLINE_EFFORT") or None

    # ---------------------------------------------------------------- server
    def ensure(self):
        with self._start_lock:
            if self.server and self.server.alive:
                return self.server
            s = AppServer(client_name="Codex Desktop", log=log)
            s.listeners.append(self._notify)
            s.server_request_handler = self._server_request
            s.start()
            self.server = s
            self.active_turn.clear()
            log("app-server started:", s.exe)
            return s

    def describe(self):
        alive = bool(self.server and self.server.alive)
        return f"Codex threads via app-server ({'running' if alive else 'starts on demand'})"

    def _server_request(self, method, params):
        # Guest threads never get escalated permissions: decline every approval request.
        log("server request", method)
        if "approval" in method.lower() or method.endswith("requestApproval"):
            return {"decision": "decline"}
        if method == "item/tool/requestUserInput":
            return {"answers": {}}
        raise RuntimeError(f"toxline can't answer {method}")

    def _notify(self, method, p):
        tid = p.get("threadId") or (p.get("thread") or {}).get("id")
        if method == "turn/started" and tid:
            self.active_turn[tid] = p["turn"]["id"]
            self.turn_done.setdefault(tid, threading.Event()).clear()
            self._emit(tid, "turn_started", {"turn_id": p["turn"]["id"]})
        elif method == "turn/completed" and tid:
            self.active_turn.pop(tid, None)
            ev = self.turn_done.setdefault(tid, threading.Event())
            ev.set()
            turn = p.get("turn") or {}
            self._emit(tid, "turn_completed", {"status": turn.get("status"), "error": turn.get("error")})
            # Let go of the thread so Codex Desktop can open it.
            threading.Thread(target=self._release, args=(tid,), daemon=True).start()
        elif method in ("item/started", "item/completed") and tid:
            item = p.get("item") or {}
            self._emit(tid, method.replace("/", "_"), _summarize_item(item))

    def _emit(self, tid, kind, data):
        if self.on_activity:
            try:
                self.on_activity(tid, kind, data)
            except Exception as e:
                log("activity hook error", e)

    def _release(self, tid):
        time.sleep(0.5)
        if tid in self.active_turn:
            return
        try:
            self.server.request("thread/unsubscribe", {"threadId": tid}, timeout=10)
        except Exception:
            pass

    # --------------------------------------------------------------- threads
    def brief(self, contact):
        from . import config
        cfg = config.load()
        role = contact.get("role") or "person"
        notes = (contact.get("notes") or "").strip()
        if role == "consult":
            about = notes or f"(none yet: wait for {cfg['owner']} to tell you what to find out)"
        else:
            about = f"Name: {contact['name']}\n{notes or '(no notes about this guest)'}"
        lib = cfg["library_map"] if role != "consult" else ""
        return config.fill(
            self.brief_template(contact),
            name=contact["name"],
            drafts=str(dbmod.HOME / "drafts"),
            tox_send=self.tox_send_cmd(),
            about=about,
            topic_clause=f" about {cfg['topic']}" if cfg["topic"] else "",
            library_clause=(f"Ground your answers in the reference material. Start from `{lib}` and read "
                            f"before answering anything specific.\n" if lib else
                            "Ground your answers in what you can actually read and verify.\n"))

    def create_thread(self, contact):
        s = self.ensure()
        cwd = GUEST_ROOT / contact["id"]
        cwd.mkdir(parents=True, exist_ok=True)
        (cwd / "README.md").write_text(
            f"Working folder for the Toxline guest thread with {contact['name']}.\n"
            f"Send them messages with: {TOX_SEND} \"text\"\n", encoding="utf-8")
        params = {"cwd": str(cwd), "approvalPolicy": "never", "sandbox": "workspace-write",
                  "config": SANDBOX_CONFIG,
                  "developerInstructions": self.brief(contact), "threadSource": "user"}
        if self.model:
            params["model"] = self.model
        r = s.request("thread/start", params)
        tid = r["thread"]["id"]
        try:
            s.request("thread/name/set", {"threadId": tid, "name": f"Tox · {contact['name']}"})
        except RpcError as e:
            log("name/set failed", e)
        # A first turn makes the thread real on disk (and visible in Codex Desktop) right away.
        self._start_turn(tid, (
            f"[Toxline] This thread is now connected to {contact['name']} over Tox. "
            f"Run `{self.tox_send_cmd()} --who` in PowerShell to confirm the connection. " + self.opening(contact)))
        return tid

    def list_threads(self, q=""):
        s = self.ensure()
        out, cursor = [], None
        for _ in range(3):
            params = {"limit": 100, "sortKey": "updated_at"}
            if cursor:
                params["cursor"] = cursor
            r = s.request("thread/list", params)
            for t in r.get("data", []):
                title = t.get("name") or t.get("preview") or ""
                if q and q.lower() not in title.lower():
                    continue
                out.append({"id": t["id"], "title": title[:120], "cwd": t.get("cwd"),
                            "updated_at": t.get("updatedAt")})
            cursor = r.get("nextCursor")
            if not cursor:
                break
        return out

    def open_thread(self, thread_id):
        os.startfile(f"codex://threads/{thread_id}")
        return {"ok": True, "note": "Opened in Codex. While it's open there, new guest messages wait until you switch away."}

    def read_thread(self, thread_id, limit_turns=30):
        """Full private transcript for the viewer's Agent tab (works even while Desktop has it open)."""
        s = self.ensure()
        r = s.request("thread/read", {"threadId": thread_id, "includeTurns": True})
        turns = (r.get("thread") or {}).get("turns") or []
        out = []
        for t in turns[-limit_turns:]:
            items = t.get("items") or []
            if t.get("itemsView") == "notLoaded" or not items:
                try:
                    items = s.request("thread/items/list", {"threadId": thread_id, "turnId": t["id"]}).get("data", [])
                except RpcError:
                    items = []
            out.append({"id": t["id"], "status": t.get("status"), "startedAt": t.get("startedAt"),
                        "items": [_summarize_item(i) for i in items]})
        return out

    # -------------------------------------------------------------- delivery
    def deliver(self, contact, message):
        return self.submit(contact["thread_id"], self.envelope(contact, message))

    def submit(self, tid, text, retry_locked=True, max_wait=None):
        """Put `text` into thread `tid` now. Steers a running turn, otherwise starts one."""
        if not tid:
            return {"state": "pending", "detail": "guest has no agent thread"}
        s = self.ensure()
        started = time.time()
        while True:
            try:
                turn_id = self.active_turn.get(tid)
                if turn_id:
                    try:
                        s.request("turn/steer", {"threadId": tid, "expectedTurnId": turn_id,
                                                 "input": [_text(text)]})
                        return {"state": "delivered_to_thread", "detail": "added to the agent's running turn"}
                    except RpcError as e:
                        log("steer failed, starting a turn instead:", e)
                        self.active_turn.pop(tid, None)
                self._start_turn(tid, text)
                return {"state": "delivered_to_thread", "detail": "started an agent turn"}
            except RpcError as e:
                if LOCKED in str(e) and retry_locked:
                    if max_wait is not None and time.time() - started > max_wait:
                        return {"state": "waiting_for_desktop", "detail": "thread is open in Codex Desktop"}
                    self._emit(tid, "locked", {"since": started})
                    time.sleep(10)
                    continue
                raise

    def _start_turn(self, tid, text):
        s = self.ensure()
        try:
            return s.request("turn/start", {"threadId": tid, "input": [_text(text)]})
        except RpcError as e:
            if "not found" not in str(e) and "not loaded" not in str(e).lower():
                raise
        # Not loaded in our server yet: resume (takes the writer lock), then start.
        s.request("thread/resume", {"threadId": tid, "excludeTurns": True,
                                    "approvalPolicy": "never", "sandbox": "workspace-write",
                                    "config": SANDBOX_CONFIG})
        return s.request("turn/start", {"threadId": tid, "input": [_text(text)]})

    def busy(self, tid):
        return tid in self.active_turn


def _text(t):
    return {"type": "text", "text": t, "text_elements": []}


def _summarize_item(item):
    t = item.get("type")
    d = {"type": t, "id": item.get("id")}
    if t == "userMessage":
        d["text"] = "\n".join(c.get("text", "") for c in item.get("content", []) if c.get("type") == "text")
    elif t == "agentMessage":
        d["text"] = item.get("text", "")
    elif t == "reasoning":
        d["text"] = "\n".join(item.get("summary") or [])[:2000]
    elif t == "commandExecution":
        d["command"] = item.get("command")
        d["status"] = item.get("status")
        d["exitCode"] = item.get("exitCode")
        out = item.get("aggregatedOutput") or ""
        d["output"] = out[-1500:]
    elif t in ("mcpToolCall", "dynamicToolCall"):
        d["tool"] = f"{item.get('server', '')}.{item.get('tool', '')}".strip(".")
        d["status"] = item.get("status")
    elif t == "fileChange":
        d["files"] = [c.get("path") for c in item.get("changes", [])]
    elif t == "webSearch":
        d["query"] = item.get("query")
    return d
