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
    if os.name != "nt":
        return None     # Codex Desktop's pipe is Windows-only; elsewhere toxline uses its app-server
    for name in os.listdir(PIPE_DIR):
        if not name.startswith(PREFIX):
            continue
        path = PIPE_DIR + name
        try:
            tools = (rpc(path, "tools/list", {"threadStartKind": "all"}, timeout=8) or {}).get("tools", [])
        except Exception:
            continue
        if any(t.get("name") == "send_message_to_thread" for t in tools):
            return path
    return None


def any_desktop_thread():
    """A fresh install has no thread of its own yet, and Desktop's thread tools need a real
    calling thread. Borrow the newest Codex Desktop thread just to create Toxline's own."""
    import sqlite3
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    for db in sorted(home.glob("state_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            r = c.execute("select id from threads where archived=0 order by "
                          "(source='vscode') desc, updated_at desc limit 1").fetchone()
            c.close()
        except sqlite3.Error:
            continue
        if r:
            return r[0]
    return None


class DesktopIngress(CodexIngress):
    """send_message_to_thread through Desktop. If Desktop isn't running, fall back to
    toxline's own app-server (which works only while the thread isn't open in Desktop)."""
    name = "codex-desktop"

    def __init__(self, journal, port):
        super().__init__(journal, port)
        self._pipe = None
        self._pipe_lock = threading.Lock()
        self._probed_at = 0      # when find_pipe last came up empty (probing costs seconds)
        self._delivered = {}     # thread_id -> when we last delivered into it (typing stays on until handled)

    def pipe(self, refresh=False):
        with self._pipe_lock:
            if refresh or not self._pipe:
                if not self._pipe and time.time() - self._probed_at < 5:
                    return None      # just looked and found nothing; don't stall callers again
                self._pipe = find_pipe()
                self._probed_at = 0 if self._pipe else time.time()
                log("Desktop app-tools pipe:", self._pipe or "not found")
            return self._pipe

    def describe(self):
        # Reads the cached pipe only: the viewer asks often and must never wait on a probe.
        return ("Codex Desktop (send_message_to_thread)" if self._pipe
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

    def _via_desktop(self, tid, text):
        for attempt in range(2):
            path = self.pipe(refresh=attempt > 0)
            if not path:
                return None
            try:
                self._call(path, tid, text)
                # Desktop has started (or steered into) a turn; the watcher reports when it ends.
                self._delivered[tid] = time.time()
                self._emit(tid, "turn_started", {})
                return {"state": "delivered_to_thread", "detail": "Codex Desktop send_message_to_thread"}
            except TimeoutError:
                # The call may still have gone through (Desktop was slow to answer). Resending
                # would risk a duplicate, so count it as delivered and say it's unconfirmed.
                log("Desktop pipe call timed out; treating as delivered (unconfirmed)")
                self._delivered[tid] = time.time()
                return {"state": "delivered_to_thread",
                        "detail": "Codex Desktop didn't confirm in time; it most likely went in"}
            except (OSError, ConnectionError) as e:
                log("Desktop pipe call failed, re-discovering:", e)
            except RuntimeError as e:
                log("Desktop refused delivery:", e)
                if "active writer" in str(e):
                    # Desktop is up; something else holds the thread (often toxline's own fallback).
                    return {"writer_busy": True}
                return None
        return None

    def submit(self, tid, text, retry_locked=True, max_wait=None):
        if not tid:
            return {"state": "pending", "detail": "guest has no agent thread"}
        started = time.time()
        while True:
            r = self._via_desktop(tid, text)
            if r and r.get("writer_busy"):
                # Desktop is running, so Desktop should deliver. If our own fallback service still holds
                # this thread (from a Desktop outage, or a thread it just created), let go and retry:
                # the runtime frees it shortly after. Never take it over with the fallback here.
                self.release_own(tid)
                if not retry_locked or (max_wait is not None and time.time() - started > max_wait):
                    return {"state": "waiting_for_desktop",
                            "detail": "another Codex window or service is using this thread; retrying"}
                self._emit(tid, "locked", {"since": started})
                time.sleep(10)
                continue
            if r:
                return r
            log("Codex Desktop unavailable; trying the app-server fallback")
            r = super().submit(tid, text, retry_locked=retry_locked,
                               max_wait=30 if retry_locked else max_wait)
            if r["state"] != "waiting_for_desktop" or not retry_locked:
                return r
            # Desktop holds the thread, so Desktop is running and its pipe was only briefly
            # unreachable (it stalls while busy). Go back to it rather than waiting on the lock.
            if max_wait is not None and time.time() - started > max_wait:
                return r
            self._pipe = None

    def release_own(self, tid):
        """Make toxline's own app-server let go of a thread so Codex Desktop can write to it."""
        if not (self.server and self.server.alive) or tid in self.active_turn:
            return   # nothing of ours, or our fallback is mid-turn (it releases when the turn ends)
        try:
            self.server.request("thread/unsubscribe", {"threadId": tid}, timeout=10)
        except Exception:
            pass

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

    def create_thread(self, contact):
        """A new, visible Codex Desktop thread for this guest, seeded with the current brief.

        The brief is the persona template filled from config (owner, topic, reference map) plus
        the guest's notes, so updating Settings updates every future guest without pasteovers."""
        caller = self.j.get("home_thread") or next(
            (c["thread_id"] for c in self.j.contacts() if c.get("thread_id")), None) or any_desktop_thread()
        if not caller or not self.pipe():
            return super().create_thread(contact)   # no Desktop: toxline's own app-server
        if not self.j.get("home_thread"):
            caller = self.home_thread(caller)
        from . import config
        cfg = config.load()
        reads = config.reference(contact.get("role") or "person", contact.get("tier") or "story")[1]
        if contact.get("role") == "public" and config.learned_file().exists():
            reads = reads + [config.learned_file()]
        first = ("Before your first reply, read " + ", ".join(f"`{r}`" for r in reads) + ". ") if reads else ""
        prompt = self.brief(contact) + "\n\n---\n\n" + self.handoff(contact) + first + self.opening(contact)
        here = str(Path(__file__).resolve().parent.parent).lower()
        projects = self._tool("list_projects", {}, caller).get("projects", [])
        proj = max((p for p in projects if here.startswith(p["path"].lower().rstrip("\\") + "\\")),
                   key=lambda p: len(p["path"]), default=None)
        target = ({"type": "project", "projectId": proj["projectId"], "environment": {"type": "local"}}
                  if proj else {"type": "projectless", "directoryName": f"tox-{contact['id']}"})
        title = "Tox · public agent" if contact.get("role") == "public" else f"Tox · {contact['name']}"
        r = self._tool("create_thread", {"title": title, "prompt": prompt,
                                         "target": target}, caller)
        log("created Desktop thread for", contact["name"], r.get("threadId"))
        return r["threadId"]

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
        # Desktop requires a target; a toxline folder that isn't a Codex project gets a projectless thread.
        args["target"] = ({"type": "project", "projectId": proj["projectId"], "environment": {"type": "local"}}
                          if proj else {"type": "projectless", "directoryName": "toxline-service"})
        hid = self._tool("create_thread", args, any_thread)["threadId"]
        self.j.put("home_thread", hid)
        return hid

    def watch(self, get_threads):
        """Follow guest threads live; emits turn_started/turn_completed for typing indicators."""
        def loop():
            cursors = {}
            while True:
                threads = [t for t in get_threads() if t][:8]
                if not self.pipe() or not threads:   # probing first keeps the viewer's status current
                    time.sleep(5)
                    continue
                try:
                    home = self.home_thread(threads[0])
                    targets = [dict({"threadId": t}, **({"afterCursor": cursors[t]} if t in cursors else {}))
                               for t in threads]
                    r = self._tool("wait_threads", {"targets": targets, "timeoutMs": 20000}, home, timeout=130)
                    for poll in (r.get("polls") or []) if isinstance(r, dict) else []:
                        tid = (poll.get("thread") or {}).get("id")
                        if not tid:
                            continue
                        cursors[tid] = poll.get("cursor") or cursors.get(tid)
                        turn = poll.get("latestTurn") or {}
                        running = (poll.get("thread") or {}).get("status", {}).get("type") == "active" or \
                            turn.get("status") == "inProgress"
                        if running:
                            continue
                        since = self._delivered.get(tid)
                        done_at = turn.get("completedAt") or 0
                        # A poll can land before Desktop has even started the turn for our message:
                        # only call it finished once a turn completed after we delivered (or it's stale).
                        if since and done_at < since - 1 and time.time() - since < 600:
                            continue
                        self._delivered.pop(tid, None)
                        self._emit(tid, "turn_completed", {})
                except Exception as e:
                    log("watch error:", e)
                    self._pipe = None
                    time.sleep(5)
        threading.Thread(target=loop, daemon=True, name="desktop-watch").start()

    def busy(self, thread_id):
        return False

    def archive_thread(self, thread_id):
        """Archive a thread in Codex Desktop (it can be unarchived there; nothing is erased)."""
        if not self.pipe():
            return False
        r = self._tool("set_thread_archived", {"threadId": thread_id, "archived": True},
                       self.j.get("home_thread") or thread_id)
        return bool(isinstance(r, dict) and r.get("archived"))

    def open_thread(self, thread_id):
        os.startfile(f"codex://threads/{thread_id}")
        return {"ok": True, "note": "Opened in Codex"}

    def read_thread(self, thread_id, limit_turns=10):
        """The agent's recent turns, oldest first: what it said privately and what it ran."""
        # Desktop only: loading the thread in toxline's own app-server could make Desktop refuse it later.
        if not self.pipe():
            return []
        from .codex_ingress import _summarize_item
        caller = self.j.get("home_thread") or thread_id
        try:
            r = self._tool("read_thread", {"threadId": thread_id, "turnLimit": max(1, min(int(limit_turns), 10))}, caller)  # Desktop caps it at 10
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            log("read_thread failed:", e)
            self._pipe = None
            return []
        if not isinstance(r, dict):
            return []
        turns = r.get("turns") or []
        if (r.get("page") or {}).get("order") == "newest_first":
            turns = list(reversed(turns))
        out = []
        for t in turns:
            items = [_summarize_item(i) for i in t.get("items") or []
                     if i.get("type") in ("userMessage", "agentMessage", "commandExecution", "fileChange")]
            out.append({"id": t.get("id"), "status": t.get("status"), "startedAt": t.get("startedAt"),
                        "completedAt": t.get("completedAt"), "items": items})
        return out
