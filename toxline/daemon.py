"""toxlined: the always-on service.

Owns the Tox node, the journal, delivery into Codex threads, the tox-send API
and the viewer. One process, one journal, one Tox identity for every guest.
"""
import argparse
import os
import queue
import re
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from . import config
from . import db as dbmod
from .httpserver import App, HttpError
from .ingress import ROLES
from .transport import LoopbackTransport

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("TOXLINE_PORT", "8765"))


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def norm_thread(t):
    """Accept a thread UUID or codex:// link in any case; 'new' means create one."""
    t = (t or "").strip()
    if t in ("", "new"):
        return "new"
    m = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", t)
    if not m:
        raise HttpError(400, "that doesn't look like a Codex thread ID")
    return m.group(0).lower()


def tox_checksum_ok(tox_id):
    """A Tox ID's last 2 bytes are the XOR of the preceding 36 bytes taken in pairs."""
    b = bytes.fromhex(tox_id)
    x0 = x1 = 0
    for i in range(0, 36, 2):
        x0 ^= b[i]
        x1 ^= b[i + 1]
    return (x0, x1) == (b[36], b[37])


def slugify(name, taken):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "guest"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


class SavedDict(dict):
    """A dict that persists itself in the journal (so pending friend requests survive restarts)."""

    def __init__(self, journal, key):
        super().__init__(journal.get(key, {}))
        self._j, self._key = journal, key

    def _save(self):
        self._j.put(self._key, dict(self))

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._save()

    def pop(self, k, *default):
        r = super().pop(k, *default)
        self._save()
        return r


class Service:
    def __init__(self, journal, tox, ingress):
        self.j = journal
        self.tox = tox                     # ToxTransport or None
        self.loop = LoopbackTransport()    # simulated guests for testing
        self.ingress = ingress
        self.requests = SavedDict(journal, "friend_requests")   # pk -> pending request from a stranger
        self.self_status = "none"
        self._lanes = {}                   # contact_id -> Queue for ordered inbound delivery
        self._lanes_lock = threading.Lock()
        self._typing = {}                  # contact_id -> bool, what the guest currently sees
        self._parts = {}                   # pk -> partial long message being reassembled
        self._send_lock = threading.Lock()  # budget check and the message it counts happen together
        for t in [self.loop] + ([tox] if tox else []):
            t.on_message = lambda pk, text, t=t: self._incoming(t, pk, text)
            t.on_receipt = lambda pk, mid, t=t: self._receipt(t, pk, mid)
            t.on_connection = lambda pk, st, t=t: self._connection(t, pk, st)
            t.on_friend_request = lambda pk, msg, t=t: self._friend_request(t, pk, msg)
            t.on_friend_name = lambda pk, name: self._friend_name(pk, name)
        if tox:
            tox.on_self_connection = self._self_connection
        ingress.on_activity = self._activity

    # ---------------------------------------------------------------- utils
    def transport_for(self, contact):
        if contact["kind"] == "test":
            return self.loop
        if not self.tox:
            raise HttpError(503, "Tox transport is not running")
        return self.tox

    def start(self):
        # Messages that were sent but never confirmed died with the last Tox session
        # (toxcore keeps unconfirmed messages only in memory). Send them again.
        for m in self.j.messages_in_state("out", ["sent", "sending"]):
            if time.time() - m["created_at"] > 86400:
                continue   # old and probably delivered with a lost receipt; don't spam a duplicate
            self.j.set_message(m["id"], state="offline_queued",
                               detail="re-sending: not confirmed before toxline restarted")
        (dbmod.HOME / "drafts").mkdir(parents=True, exist_ok=True)   # where agents write long messages
        self.loop.start()
        if self.tox:
            self.tox.start()
            # Re-register every active guest as a friend (idempotent) so bindings survive restarts.
            for c in self.j.contacts():
                if c["kind"] == "tox":
                    try:
                        self.tox.ensure_friend(c["public_key"])
                    except Exception as e:
                        log("ensure_friend failed", c["id"], e)
        for c in self.j.contacts():
            if c["kind"] == "test":
                self.loop.add_friend(c["public_key"])
        threading.Thread(target=self._outbox_loop, daemon=True, name="outbox").start()
        if hasattr(self.ingress, "watch"):
            self.ingress.watch(lambda: list(dict.fromkeys(
                c["thread_id"] for c in self.j.contacts() if c["status"] == "active" and c["thread_id"])))

    # ------------------------------------------------------------- outbox
    OUTBOX = dbmod.HOME / "outbox"   # per instance, so test instances never answer for the live one

    def _outbox_loop(self):
        """tox-send's fallback when a sandbox blocks localhost: request files in outbox/."""
        import json as _json
        self.OUTBOX.mkdir(exist_ok=True)
        while True:
            for req in sorted(self.OUTBOX.glob("*.req.json")):
                try:
                    if time.time() - req.stat().st_mtime > 30:
                        req.unlink()        # its tox-send already reported a timeout
                        continue
                except OSError:
                    continue
                claimed = req.with_suffix(".claimed")
                try:
                    req.rename(claimed)          # atomic: only one reader wins
                    r = _json.loads(claimed.read_text(encoding="utf-8-sig"))
                    claimed.unlink()
                except Exception:
                    continue
                try:
                    if r.get("op") == "who":
                        out = self.whoami(r.get("thread_id", ""), 15)
                    else:
                        out = self.send_and_wait(r.get("body", ""), r.get("thread_id"), to=r.get("to"))
                except Exception as e:
                    out = {"error": str(e)}
                tmp = self.OUTBOX / f"{r.get('id')}.res.tmp"
                tmp.write_text(_json.dumps(out), encoding="utf-8")
                tmp.replace(self.OUTBOX / f"{r.get('id')}.res.json")
            time.sleep(0.25)

    # ------------------------------------------------------------- inbound
    # Tox caps a message at 1372 bytes, so clients split long text into parts sent back to
    # back (milliseconds apart). A part this long, followed that quickly by another, is a split;
    # people don't send a second message within 0.4 s of a 400-byte one.
    SPLIT_BYTES = 400
    SPLIT_WAIT = 0.4

    def _incoming(self, transport, pk, text):
        """Rejoin messages the guest's client split for Tox's size limit, then record."""
        with self._lanes_lock:
            buf = self._parts.get(pk)
            if buf:
                buf["timer"].cancel()
                text = buf["text"] + text
            part = len(text.encode("utf-8")) - (len(buf["text"].encode("utf-8")) if buf else 0)
            if part >= self.SPLIT_BYTES:
                t = threading.Timer(self.SPLIT_WAIT, self._flush_parts, args=(transport, pk))
                self._parts[pk] = {"text": text, "timer": t}
                t.start()
                return
            self._parts.pop(pk, None)
        self._record_incoming(transport, pk, text)

    def _flush_parts(self, transport, pk):
        with self._lanes_lock:
            buf = self._parts.pop(pk, None)
        if buf:
            self._record_incoming(transport, pk, buf["text"])

    def _record_incoming(self, transport, pk, text):
        c = self.j.contact_by_key(pk)
        if not c or c["status"] == "archived":
            self.j.event("stranger_message", None, public_key=pk, body=text)
            log("message from unknown key", pk[:12])
            return
        state = "pending" if c["status"] == "paused" or not c["thread_id"] else "delivering"
        m = self.j.add_message(c["id"], "in", text, state, thread_id=c["thread_id"])
        log(f"in  {c['id']}: {text[:60]!r}")
        if state == "delivering":
            self._lane(c["id"]).put(m["id"])

    def _lane(self, cid):
        with self._lanes_lock:
            q = self._lanes.get(cid)
            if q is None:
                q = self._lanes[cid] = queue.Queue()
                threading.Thread(target=self._lane_worker, args=(cid, q), daemon=True, name=f"lane-{cid}").start()
            return q

    def _lane_worker(self, cid, q):
        # One worker per guest keeps their messages in order; delivery starts the moment
        # a message arrives (there is no batching or idle-wait here).
        while True:
            mid = q.get()
            m = self.j.message(mid)
            c = self.j.contact(cid)
            try:
                result = self.ingress.deliver(c, m)
                self.j.set_message(mid, state=result.get("state", "delivered_to_thread"),
                                   detail=result.get("detail", ""), thread_id=c["thread_id"])
            except Exception as e:
                traceback.print_exc()
                self.j.set_message(mid, state="delivery_failed", detail=f"{type(e).__name__}: {e}")

    def redeliver(self, mid):
        m = self.j.message(mid)
        if not m or m["direction"] != "in":
            raise HttpError(404, "no such inbound message")
        self.j.set_message(mid, state="delivering", detail="")
        self._lane(m["contact_id"]).put(mid)
        return self.j.message(mid)

    def _activity(self, thread_id, kind, data):
        """Live agent activity from the ingress: drives the guests' typing indicator."""
        for c in self.j.contacts_by_thread(thread_id):
            self._activity_for(c, kind)

    def _activity_for(self, c, kind):
        if kind in ("turn_started", "turn_completed"):
            on = kind == "turn_started"
            if on:
                # Only show "typing" when the guest is actually waiting on a reply, not while
                # the owner is talking to the agent privately.
                last = self.j.messages(c["id"], limit=1)
                if not last or last[-1]["direction"] != "in":
                    return
            if self._typing.get(c["id"], False) == on:
                return
            self._typing[c["id"]] = on
            try:
                self.transport_for(c).set_typing(c["public_key"], on)
            except Exception:
                pass
            self.j.event("typing", c["id"], on=on)
        elif kind == "locked":
            for m in self.j.messages(c["id"], limit=50):
                if m["direction"] == "in" and m["state"] == "delivering":
                    self.j.set_message(m["id"], state="waiting_for_desktop",
                                       detail="the thread is open in Codex Desktop; it goes in as soon as Desktop lets go")

    # ------------------------------------------------------------ outbound
    def recipients(self, thread_id, to=None):
        """Who a tox-send from this thread goes to. Shared threads need --to (a name, id, or 'all')."""
        guests = self.j.contacts_by_thread(thread_id or "")
        if not guests:
            raise HttpError(404, f"no guest is bound to thread {thread_id}")
        names = ", ".join(g["name"] for g in guests)
        if not to:
            if len(guests) == 1:
                return guests
            raise HttpError(400, f"this thread talks to {names}; say who with --to NAME (or --to all)")
        if to.strip().lower() == "all":
            return guests
        wanted = [t.strip().lower() for t in to.split(",") if t.strip()]
        picked = []
        for w in wanted:
            g = next((g for g in guests if w in (g["id"].lower(), g["name"].lower())), None)
            if not g:
                raise HttpError(400, f"no guest called {w!r} on this thread (it talks to {names})")
            if g not in picked:
                picked.append(g)
        return picked

    def send_and_wait(self, body, thread_id, to=None, origin="agent", wait=4):
        msgs = [self.send(body, contact_id=g["id"], origin=origin) for g in self.recipients(thread_id, to)]
        deadline = time.time() + min(float(wait or 0), 30)
        while any(m["state"] in ("sending", "sent") for m in msgs) and time.time() < deadline:
            time.sleep(0.2)
            msgs = [self.j.message(m["id"]) for m in msgs]
        results = []
        for m in msgs:
            c = self.j.contact(m["contact_id"])
            results.append({"message": m, "to": {"id": c["id"], "name": c["name"]}})
        return dict(results[0], results=results)

    def whoami(self, thread_id, limit=20):
        guests = self.j.contacts_by_thread(thread_id or "")
        if not guests:
            raise HttpError(404, "this thread is not bound to a guest")
        recent = []
        for g in guests:
            for m in self.j.messages(g["id"], limit=limit):
                recent.append(dict(m, guest=g["name"]))
        recent.sort(key=lambda m: m.get("shown_at") or m["created_at"])
        return {"contact": guests[0], "contacts": guests, "recent": recent[-limit:]}

    def send(self, body, thread_id=None, contact_id=None, origin="agent"):
        body = (body or "").strip("\n")
        if not body.strip():
            raise HttpError(400, "empty message")
        if contact_id:
            c = self.j.contact(contact_id)
        else:
            c = self.recipients(thread_id)[0]
        if not c:
            raise HttpError(404, "no such guest")
        if c["status"] == "archived":
            raise HttpError(409, f"{c['name']} is archived")
        held = c["hold_outgoing"] or c["status"] == "paused"
        why = "held: outgoing on hold" if c["hold_outgoing"] else "held: bridge paused"
        with self._send_lock:
            if not held and origin != "owner" and self.over_budget(c):
                held, why = True, self.BUDGET_HELD
            m = self.j.add_message(c["id"], "out", body, "held" if held else "sending",
                                   thread_id=c["thread_id"], detail=why if held else f"from {origin}",
                                   origin=origin)
        log(f"out {c['id']}: {body[:60]!r}" + (" [held]" if held else ""))
        if not held:
            m = self._transmit(m)
        return m

    # Two agents can keep answering each other forever. In agent conversations, once our agent
    # has sent the budgeted number of messages, the rest wait for the owner; releasing one
    # starts a fresh budget.
    BUDGET_HELD = "held: message budget for this agent conversation is used up"

    def over_budget(self, c):
        if (c.get("role") or "person") == "person":
            return False
        since = self.j.get(f"budget_from:{c['id']}", 0)
        return self.j.count_out_since(c["id"], since) >= config.agent_budget()

    def _transmit(self, m):
        c = self.j.contact(m["contact_id"])
        t = self.transport_for(c)
        if not t.friend_online(c["public_key"]):
            return self.j.set_message(m["id"], state="offline_queued",
                                      detail=f"{c['name']} is offline; will send when they connect")
        try:
            # Another Toxline rejoins split parts exactly; chat apps get tidy, trimmed parts.
            ids = t.send(c["public_key"], m["body"], exact=(c.get("role") or "person") != "person")
        except Exception as e:
            return self.j.set_message(m["id"], state="failed", detail=f"{type(e).__name__}: {e}")
        if self._typing.get(c["id"]):
            self._typing[c["id"]] = False
            t.set_typing(c["public_key"], False)
            self.j.event("typing", c["id"], on=False)
        return self.j.set_message(m["id"], state="sent", tox_ids=ids, detail="")

    def release(self, mid, body=None):
        m = self.j.message(mid)
        if not m or m["state"] not in ("held", "failed", "offline_queued"):
            raise HttpError(409, "only held, failed or queued messages can be sent")
        if body is not None:
            if not body.strip():
                raise HttpError(400, "empty message")
            self.j.set_message(mid, body=body)
        with self._send_lock:
            if m["detail"] == self.BUDGET_HELD:
                # The owner let the conversation continue: a fresh budget starts after this message.
                key = f"budget_from:{m['contact_id']}"
                self.j.put(key, max(self.j.get(key, 0), m["created_at"]))
                self.j.event("budget_reset", m["contact_id"])
            elif (m["state"] == "held" and m.get("origin") != "owner"
                  and self.over_budget(self.j.contact(m["contact_id"]))):
                # Held for another reason (hold/pause) and the budget ran out meanwhile: it stays
                # held, now for the budget, so going on is a deliberate choice.
                return self.j.set_message(mid, detail=self.BUDGET_HELD)
            self.j.set_message(mid, state="sending")
        return self._transmit(self.j.message(mid))

    def discard(self, mid):
        m = self.j.message(mid)
        if not m or m["state"] not in ("held", "offline_queued", "failed"):
            raise HttpError(409, "only held, queued or failed messages can be discarded")
        return self.j.set_message(mid, state="discarded")

    def _receipt(self, transport, pk, msg_id):
        c = self.j.contact_by_key(pk)
        if not c:
            return
        for m in reversed(self.j.messages(c["id"], limit=200)):
            if m["direction"] == "out" and msg_id in m["tox_ids"]:
                acks = self.j.get(f"acks:{m['id']}", [])
                acks = sorted(set(acks) | {msg_id})
                self.j.put(f"acks:{m['id']}", acks)
                if set(acks) >= set(m["tox_ids"]):
                    self.j.set_message(m["id"], state="delivered", detail="read receipt from their client")
                return

    def _connection(self, transport, pk, status):
        c = self.j.contact_by_key(pk)
        if not c:
            return
        self.j.update_contact(c["id"], online=status)
        if status == "none":
            # Toxcore drops unconfirmed messages when the friend connection dies; requeue them.
            for m in self.j.messages(c["id"], limit=200):
                if m["direction"] == "out" and m["state"] == "sent" and not self._acked(m):
                    self.j.set_message(m["id"], state="offline_queued",
                                       detail="they went offline before confirming; re-sending when they connect")
        else:
            # Tox doesn't hold messages for offline friends; send what waited for them now.
            for m in self.j.messages(c["id"], limit=500):
                if m["direction"] == "out" and m["state"] == "offline_queued":
                    self.j.set_message(m["id"], state="sending")
                    self._transmit(self.j.message(m["id"]))

    def _acked(self, m):
        return set(self.j.get(f"acks:{m['id']}", [])) >= set(m["tox_ids"])

    def _friend_name(self, pk, name):
        c = self.j.contact_by_key(pk)
        if c and name and c.get("tox_name") != name:
            self.j.update_contact(c["id"], tox_name=name)

    def _friend_request(self, transport, pk, greeting):
        c = self.j.contact_by_key(pk)
        if c and c["status"] != "archived":
            transport.accept_request(pk)
            log("auto-accepted friend request from known guest", c["id"])
            return
        self.requests[pk] = {"public_key": pk, "greeting": greeting, "at": time.time(),
                             "agent": config.AGENT_TAG in (greeting or ""),
                             "role": c["role"] if c else None,
                             "returning": c["name"] if c else None,
                             "thread_id": c["thread_id"] if c else None}
        self.j.event("friend_request", None, public_key=pk, greeting=greeting)

    def _self_connection(self, status):
        self.self_status = status
        self.j.event("self_connection", None, status=status)

    # -------------------------------------------------------------- guests
    def add_guest(self, name, tox_id="", kind="tox", thread="new", notes="", greeting="", role=""):
        """Validate everything first, then create; roll back if a later step fails."""
        name = (name or "").strip()
        if not name:
            raise HttpError(400, "name is required")
        if kind not in ("tox", "test"):
            raise HttpError(400, "kind must be tox or test")
        if role and role not in ROLES:
            raise HttpError(400, "role must be person, agent or consult")
        thread = norm_thread(thread)
        if kind == "test":
            import secrets
            pk, tox_id = secrets.token_hex(32).upper(), None
        else:
            if not self.tox:
                raise HttpError(503, "Tox is off (toxline was started with --no-tox)")
            tox_id = re.sub(r"\s+", "", tox_id or "").upper()
            if not re.fullmatch(r"[0-9A-F]{64}([0-9A-F]{12})?", tox_id):
                raise HttpError(400, "A Tox ID is 76 hex characters (a 64-character public key also works)")
            if len(tox_id) == 76 and not tox_checksum_ok(tox_id):
                raise HttpError(400, "That Tox ID has a typo (its checksum doesn't match). Copy it again from their client.")
            pk = tox_id[:64]
            if self.tox.address() and pk == self.tox.address()[:64]:
                raise HttpError(400, "That's the agent's own Tox ID (the one at the top-left of Toxline). "
                                     "Paste the guest's ID from their client instead (in qTox: click your own "
                                     "name/avatar at top-left, then copy the Tox ID), or just have them send a "
                                     "friend request to the agent's ID and use 'Set up guest' when it appears.")
            existing = self.j.contact_by_key(pk)
            if existing and existing["status"] != "archived":
                raise HttpError(409, f"that Tox key already belongs to {existing['name']}")
            if existing:   # an archived guest coming back: restore them
                c = self.j.update_contact(existing["id"], name=name, notes=notes or existing["notes"],
                                          role=role or existing.get("role") or "person")
                if thread != c["thread_id"]:
                    self.rebind(c["id"], thread)
                self.set_status(c["id"], "active")
                self._befriend(self.j.contact(c["id"]), greeting)
                return self.j.contact(c["id"])
            if len(tox_id) == 64:
                tox_id = None
        taken = {c["id"] for c in self.j.contacts(include_archived=True)}
        cid = slugify(name, taken)
        c = self.j.add_contact(cid, name, pk, tox_id=tox_id, notes=notes, kind=kind, role=role or "person")
        try:
            self._befriend(c, greeting)
            if thread == "new":
                thread_id = self.ingress.create_thread(c)
            else:
                thread_id = thread
                self._send_brief(c, thread_id)
            return self.j.update_contact(cid, thread_id=thread_id)
        except Exception as e:
            traceback.print_exc()
            try:
                self.transport_for(c).remove_friend(pk)
            except Exception:
                pass
            self.j.delete_contact(cid)
            raise HttpError(502, f"couldn't set up {name}: {e}")

    def _befriend(self, c, greeting=""):
        t = self.transport_for(c)
        if c["kind"] == "test":
            t.add_friend(c["public_key"])
        elif c["public_key"] in self.requests:
            t.accept_request(c["public_key"])
            self.requests.pop(c["public_key"], None)
        else:
            default = config.load()["agent_greeting" if c.get("role") == "consult" else "greeting"]
            t.add_friend(c["tox_id"] or c["public_key"], greeting or config.fill(default, name=c["name"]))

    def delete_guest(self, cid):
        c = self.j.contact(cid)
        if not c:
            raise HttpError(404, "no such guest")
        if c["status"] != "archived":
            raise HttpError(409, "archive the guest before deleting them")
        try:
            self.transport_for(c).remove_friend(c["public_key"])
        except Exception:
            pass
        self.j.delete_contact(cid)
        return {"ok": True}

    def _send_brief(self, c, thread_id):
        """Tell an existing thread it now talks to this guest and how to reply."""
        others = [g["name"] for g in self.j.contacts_by_thread(thread_id) if g["id"] != c["id"]]
        text = self.ingress.connection_brief(c, others)
        threading.Thread(target=self.ingress.submit, args=(thread_id, text), daemon=True).start()

    def rebind(self, cid, thread):
        c = self.j.contact(cid)
        if not c:
            raise HttpError(404, "no such guest")
        thread = norm_thread(thread)
        if thread == "new":
            thread = self.ingress.create_thread(c)
        elif thread != c["thread_id"]:
            self._send_brief(c, thread)
        self.j.event("rebound", cid, old=c["thread_id"], new=thread)
        return self.j.update_contact(cid, thread_id=thread)

    def set_status(self, cid, status):
        c = self.j.contact(cid)
        if status not in ("active", "paused", "archived"):
            raise HttpError(400, "bad status")
        before = self.j.contact(cid)
        if not before:
            raise HttpError(404, "no such guest")
        c = self.j.update_contact(cid, status=status)
        if status == "active":
            if before["status"] == "archived":
                self._befriend(c)       # archiving removed the Tox friendship; restore it
            for m in self.j.messages(cid):
                if m["direction"] == "in" and m["state"] == "pending":
                    self.redeliver(m["id"])
                # Replies held only because the bridge was paused go out now.
                if m["direction"] == "out" and m["state"] == "held" and                         m["detail"] == "held: bridge paused" and not c["hold_outgoing"]:
                    self.release(m["id"])
        if status == "archived":
            if c["kind"] == "tox" and self.tox:
                self.tox.remove_friend(c["public_key"])
            c = self.j.update_contact(cid, online="none")
        return c

    def simulate(self, cid, body):
        c = self.j.contact(cid)
        if not c or c["kind"] != "test":
            raise HttpError(400, "only test guests can be simulated")
        if c["status"] == "archived":
            raise HttpError(409, f"{c['name']} is archived")
        if not (body or "").strip():
            raise HttpError(400, "empty message")
        self.loop.inject(c["public_key"], body)
        return {"ok": True}

    # --------------------------------------------------------------- views
    def snapshot(self):
        unread = self.j.unread_counts()
        out = []
        for c in self.j.contacts(include_archived=True):
            msgs = self.j.messages(c["id"], limit=1)
            c["last"] = msgs[-1] if msgs else None
            c["unread"] = unread.get(c["id"], 0)
            if c["kind"] == "test":
                c["online"] = "udp"
            if (c.get("role") or "person") != "person":
                since = self.j.get(f"budget_from:{c['id']}", 0)
                c["budget"] = {"used": self.j.count_out_since(c["id"], since), "limit": config.agent_budget()}
            out.append(c)
        out.sort(key=lambda c: -(c["last"]["created_at"] if c["last"] else c["created_at"]))
        return {
            "self": {
                "tox_id": self.tox.address() if self.tox else None,
                "name": self.tox.name if self.tox else None,
                "connection": self.self_status if self.tox else "disabled",
            },
            "contacts": out,
            "requests": sorted(self.requests.values(), key=lambda r: -r["at"]),
            "ingress": self.ingress.describe(),
            "seq": self.j.last_seq(),
        }


def build_app(svc):
    app = App(ROOT / "viewer")
    j = svc.j

    @app.route("GET", "/api/state")
    def state(**_):
        return svc.snapshot()

    @app.route("GET", "/api/contacts/:cid/messages")
    def messages(cid, query, **_):
        if not j.contact(cid):
            raise HttpError(404, "no such guest")
        try:
            limit = max(1, min(int(query.get("limit", 2000)), 10000))
        except ValueError:
            raise HttpError(400, "limit must be a number")
        return {"messages": j.messages(cid, limit=limit)}

    @app.route("GET", "/api/events")
    def events(req, query, **_):
        q = queue.Queue()
        unsub = j.subscribe(q.put)
        try:
            since = int(query.get("since", 0) or 0)
            return req.sse(q, initial=j.events_since(since) if since else [])
        finally:
            unsub()

    @app.route("POST", "/api/contacts")
    def add(body, **_):
        def text(k, default=""):
            v = body.get(k, default)
            if v is not None and not isinstance(v, str):
                raise HttpError(400, f"{k} must be text")
            return v or default
        return svc.add_guest(text("name"), text("tox_id"), text("kind", "tox"), text("thread", "new"),
                             text("notes"), text("greeting"), text("role"))

    @app.route("POST", "/api/contacts/:cid/update")
    def update(cid, body, **_):
        if not j.contact(cid):
            raise HttpError(404, "no such guest")
        if "status" in body:
            svc.set_status(cid, body.pop("status"))
        allowed = {k: body[k] for k in ("name", "notes", "hold_outgoing", "role") if k in body}
        if "role" in allowed and allowed["role"] not in ROLES:
            raise HttpError(400, "role must be person, agent or consult")
        for k in ("name", "notes"):
            if k in allowed and not isinstance(allowed[k], str):
                raise HttpError(400, f"{k} must be text")
        if "hold_outgoing" in allowed:
            allowed["hold_outgoing"] = 1 if allowed["hold_outgoing"] else 0
        return j.update_contact(cid, **allowed)

    @app.route("POST", "/api/contacts/:cid/delete")
    def delete(cid, **_):
        return svc.delete_guest(cid)

    @app.route("POST", "/api/contacts/:cid/rebind")
    def rebind(cid, body, **_):
        return svc.rebind(cid, body.get("thread", "new"))

    @app.route("POST", "/api/contacts/:cid/seen")
    def seen(cid, **_):
        j.mark_seen(cid)
        j.event("seen", cid)
        return {"ok": True}

    @app.route("POST", "/api/contacts/:cid/simulate")
    def simulate(cid, body, **_):
        return svc.simulate(cid, body.get("body", ""))

    @app.route("POST", "/api/contacts/:cid/open")
    def open_thread(cid, **_):
        c = j.contact(cid)
        if not c or not c["thread_id"]:
            raise HttpError(404, "guest has no thread")
        return svc.ingress.open_thread(c["thread_id"])

    @app.route("POST", "/api/send")
    def send(body, **_):
        if not isinstance(body, dict) or not isinstance(body.get("body", ""), str):
            raise HttpError(400, "body must be a JSON object with a text 'body'")
        if body.get("contact_id"):
            m = svc.send(body.get("body", ""), contact_id=body["contact_id"], origin=body.get("origin", "owner"))
            c = j.contact(m["contact_id"])
            r = {"message": m, "to": {"id": c["id"], "name": c["name"]}}
            return dict(r, results=[r])
        to = body.get("to")
        if to is not None and not isinstance(to, str):
            raise HttpError(400, "to must be text")
        try:
            wait = float(body.get("wait", 0) or 0)
        except (TypeError, ValueError):
            wait = 0
        return svc.send_and_wait(body.get("body", ""), body.get("thread_id"), to=to,
                                 origin=body.get("origin", "agent"), wait=wait)

    @app.route("GET", "/api/whoami")
    def whoami(query, **_):
        try:
            limit = max(1, min(int(query.get("limit", 20)), 500))
        except ValueError:
            raise HttpError(400, "limit must be a number")
        return svc.whoami(query.get("thread_id", ""), limit)

    @app.route("GET", "/api/messages/:mid")
    def message(mid, **_):
        m = j.message(mid)
        if not m:
            raise HttpError(404, "no such message")
        return m

    @app.route("POST", "/api/messages/:mid/release")
    def release(mid, body, **_):
        return svc.release(mid, body.get("body"))

    @app.route("POST", "/api/messages/:mid/discard")
    def discard(mid, **_):
        return svc.discard(mid)

    @app.route("POST", "/api/messages/:mid/redeliver")
    def redeliver(mid, **_):
        return svc.redeliver(mid)

    @app.route("POST", "/api/requests/:pk/dismiss")
    def dismiss(pk, **_):
        svc.requests.pop(pk.upper(), None)
        j.event("request_dismissed", None, public_key=pk)
        return {"ok": True}

    @app.route("GET", "/api/threads")
    def threads(query, **_):
        return {"threads": svc.ingress.list_threads(query.get("q", ""))}

    @app.route("GET", "/api/settings")
    def get_settings(**_):
        return config.load()

    @app.route("POST", "/api/settings")
    def settings(body, **_):
        if not isinstance(body, dict):
            raise HttpError(400, "settings must be a JSON object")
        before = config.load()
        cfg = config.save({k: v for k, v in body.items() if isinstance(v, str)})
        if svc.tox and (cfg["guide_name"], cfg["status_message"]) != (before["guide_name"], before["status_message"]):
            svc.tox.set_name(cfg["guide_name"][:120], cfg["status_message"][:200])
        j.event("settings", None)
        return cfg

    @app.route("GET", "/api/persona")
    def persona(**_):
        return {"text": svc.ingress.persona_text()}

    @app.route("POST", "/api/persona")
    def set_persona(body, **_):
        svc.ingress.set_persona_text(body.get("text", ""))
        return {"ok": True}

    return app


def main(argv=None):
    ap = argparse.ArgumentParser(prog="toxlined")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-tox", action="store_true", help="run with only simulated guests")
    ap.add_argument("--ingress", default=os.environ.get("TOXLINE_INGRESS", "desktop"))
    ap.add_argument("--open", action="store_true", help="open the viewer when ready")
    args = ap.parse_args(argv)

    if sys.stdout is None:   # started windowless (pythonw / autostart): log to a file
        dbmod.HOME.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(dbmod.HOME / "toxline.log", "a", encoding="utf-8", buffering=1)

    journal = dbmod.Journal()
    from .ingress import make_ingress
    ingress = make_ingress(args.ingress, journal, port=args.port)
    tox = None
    if not args.no_tox:
        from .tox_transport import ToxTransport
        cfg = config.load()
        tox = ToxTransport(dbmod.HOME / "tox", name=cfg["guide_name"], status_message=cfg["status_message"])
    svc = Service(journal, tox, ingress)
    svc.start()
    build_app(svc).serve("127.0.0.1", args.port)
    url = f"http://127.0.0.1:{args.port}/"
    log("toxline viewer at", url, "| tox", tox.address() if tox else "disabled", "| ingress", args.ingress)
    if args.open:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        if tox:
            tox.stop()


if __name__ == "__main__":
    sys.exit(main())
