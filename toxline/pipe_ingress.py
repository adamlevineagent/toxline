"""Desktop ingress: deliver through Codex Desktop's own `send_message_to_thread`.

Codex Desktop serves its codex_app tools (send_message_to_thread, read_thread, ...) to its
agents over a local named pipe. Calling send_message_to_thread there makes Desktop itself
deliver the message: it steers into the thread's running turn if there is one (landing at
the agent's next tool boundary), otherwise starts a turn. It never uses the follow-up queue,
and the thread updates live in Desktop whether or not it's open.

Wire format (from the installed Desktop source): each frame is a 4-byte little-endian
length followed by a UTF-8 JSON-RPC 2.0 message. The pipe name is random per Desktop
launch, so toxline finds it by asking each candidate pipe for its tool list.
"""
import json
from pathlib import Path
import os
import struct
import threading
import time
import uuid

from .codex_ingress import CodexIngress, log

PIPE_DIR = "\\\\.\\pipe\\"
PREFIX = "codex-browser-use-"


def _frame(f, msg):
    data = json.dumps(msg).encode("utf-8")
    f.write(struct.pack("<I", len(data)) + data)


def _read_exact(f, n):
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            raise ConnectionError("pipe closed")
        buf += chunk
    return buf


def rpc(path, method, params=None, timeout=60):
    """One request per connection: robust across Desktop restarts, no shared state."""
    msg = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": method}
    if params is not None:
        msg["params"] = params
    box = {}

    def go():
        try:
            with open(path, "r+b", buffering=0) as f:
                _frame(f, msg)
                while True:
                    n = struct.unpack("<I", _read_exact(f, 4))[0]
                    reply = json.loads(_read_exact(f, n).decode("utf-8"))
                    if reply.get("id") == msg["id"]:
                        box["reply"] = reply
                        return
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout)
    if "error" in box:
        raise box["error"]
    if "reply" not in box:
        raise TimeoutError(f"{method} timed out on {path}")
    reply = box["reply"]
    if "error" in reply:
        raise RuntimeError(reply["error"].get("message", str(reply["error"])))
    return reply.get("result")


def find_pipe():
    for name in os.listdir(PIPE_DIR):
        if not name.startswith(PREFIX):
            continue
        path = PIPE_DIR + name
        try:
            tools = (rpc(path, "tools/list", {"threadStartKind": "all"}, timeout=3) or {}).get("tools", [])
        except Exception:
            continue
        if any(t.get("name") == "send_message_to_thread" for t in tools):
            return path
    return None


class DesktopIngress(CodexIngress):
    """send_message_to_thread through Desktop. If Desktop isn't running, fall back to
    toxline's own app-server (which works only while the thread isn't open in Desktop)."""
    name = "codex-desktop"

    def __init__(self, journal, port):
        super().__init__(journal, port)
        self._pipe = None
        self._pipe_lock = threading.Lock()

    def pipe(self, refresh=False):
        with self._pipe_lock:
            if refresh or not self._pipe:
                self._pipe = find_pipe()
                log("Desktop app-tools pipe:", self._pipe or "not found")
            return self._pipe

    def describe(self):
        return ("Codex Desktop (send_message_to_thread)" if self.pipe()
                else "Codex app-server fallback (Codex Desktop not found)")

    def _call(self, path, tid, text):
        params = {"namespace": "codex_app", "tool": "send_message_to_thread",
                  "arguments": {"threadId": tid, "prompt": text}, "callerSource": "codex",
                  "callId": "toxline-" + uuid.uuid4().hex, "hostId": "local",
                  # Desktop wants a real calling thread; the target itself is accepted.
                  "threadId": tid, "turnId": "toxline-" + uuid.uuid4().hex[:12]}
        r = rpc(path, "tools/call", params, timeout=90) or {}
        if not r.get("success", True):
            raise RuntimeError(json.dumps(r)[:300])
        return r

    def submit(self, tid, text, retry_locked=True, max_wait=None):
        if not tid:
            return {"state": "pending", "detail": "guest has no agent thread"}
        for attempt in range(2):
            path = self.pipe(refresh=attempt > 0)
            if not path:
                break
            try:
                self._call(path, tid, text)
                # Desktop has started (or steered into) a turn; the watcher reports when it ends.
                self._emit(tid, "turn_started", {})
                return {"state": "delivered_to_thread", "detail": "Codex Desktop send_message_to_thread"}
            except (OSError, ConnectionError, TimeoutError) as e:
                log("Desktop pipe call failed, re-discovering:", e)
            except RuntimeError as e:
                # Desktop refused (e.g. toxline's own app-server still holds a thread it just made).
                log("Desktop refused delivery:", e)
                break
        log("Codex Desktop unavailable; using app-server fallback")
        return super().submit(tid, text, retry_locked=retry_locked, max_wait=max_wait)

    # ------------------------------------------------------------ watching
    def _tool(self, tool, args, caller, timeout=90):
        path = self.pipe()
        if not path:
            raise ConnectionError("Codex Desktop not found")
        r = rpc(path, "tools/call", {"namespace": "codex_app", "tool": tool, "arguments": args,
                                     "callerSource": "codex", "callId": "toxline-" + uuid.uuid4().hex,
                                     "hostId": "local", "threadId": caller,
                                     "turnId": "toxline-" + uuid.uuid4().hex[:12]}, timeout=timeout) or {}
        text = (r.get("contentItems") or [{}])[0].get("text", "")
        if not r.get("success", False):
            raise RuntimeError(text[:300])
        try:
            return json.loads(text)
        except ValueError:
            return text

    def home_thread(self, any_thread):
        """A small 'Toxline service' thread used only as the caller for wait_threads
        (Desktop won't let a thread wait on itself)."""
        hid = self.j.get("home_thread")
        if hid:
            return hid
        projects = self._tool("list_projects", {}, any_thread).get("projects", [])
        here = str(Path(__file__).resolve().parent.parent).lower()
        proj = next((p for p in projects if here.startswith(p["path"].lower().rstrip("\\") + "\\")), None)
        args = {"title": "Toxline service",
                "prompt": "This thread exists so Toxline can watch guest threads. Nothing to do here; reply with one word: ok."}
        if proj:
            args["target"] = {"type": "project", "projectId": proj["projectId"], "environment": {"type": "local"}}
        hid = self._tool("create_thread", args, any_thread)["threadId"]
        self.j.put("home_thread", hid)
        return hid

    def watch(self, get_threads):
        """Follow guest threads live; emits turn_started/turn_completed for typing indicators."""
        def loop():
            cursors = {}
            while True:
                threads = [t for t in get_threads() if t][:8]
                if not threads or not self.pipe():
                    time.sleep(5)
                    continue
                try:
                    home = self.home_thread(threads[0])
                    targets = [dict({"threadId": t}, **({"afterCursor": cursors[t]} if t in cursors else {}))
                               for t in threads]
                    r = self._tool("wait_threads", {"targets": targets, "timeoutMs": 60000}, home, timeout=130)
                    for poll in (r.get("polls") or []) if isinstance(r, dict) else []:
                        tid = (poll.get("thread") or {}).get("id")
                        if not tid:
                            continue
                        cursors[tid] = poll.get("cursor") or cursors.get(tid)
                        running = (poll.get("thread") or {}).get("status", {}).get("type") == "active" or \
                            (poll.get("latestTurn") or {}).get("status") == "inProgress"
                        if not running:
                            self._emit(tid, "turn_completed", {})
                except Exception as e:
                    log("watch error:", e)
                    self._pipe = None
                    time.sleep(5)
        threading.Thread(target=loop, daemon=True, name="desktop-watch").start()

    def busy(self, thread_id):
        return False

    def open_thread(self, thread_id):
        os.startfile(f"codex://threads/{thread_id}")
        return {"ok": True, "note": "Opened in Codex"}

    def read_thread(self, thread_id, limit_turns=10):
        return []
