"""The journal: one SQLite file that is the single source of truth.

Every Tox message in or out, every delivery attempt and every receipt lands
here. The viewer, the CLI and the daemon all read the same rows, so the
"W experience" view can never disagree with what actually happened.
"""
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

HOME = Path(os.environ.get("TOXLINE_HOME", Path(__file__).resolve().parent.parent / "state"))
DB_PATH = HOME / "toxline.sqlite3"

SCHEMA = """
create table if not exists contacts (
  id            text primary key,          -- short slug, e.g. 'w'
  name          text not null,             -- display name you chose
  public_key    text not null unique,      -- 64-hex Tox public key (identity)
  tox_id        text,                      -- full 76-hex address if known
  kind          text not null default 'tox',      -- tox | test (test = simulated person, typed from the viewer)
  thread_id     text,                      -- bound Codex thread (guests may share one)
  status        text not null default 'active',   -- active | paused | archived
  hold_outgoing integer not null default 0,
  tox_name      text,                      -- name their client advertises
  online        text not null default 'none',     -- none | udp | tcp
  notes         text not null default '',
  created_at    real not null,
  updated_at    real not null
);
create table if not exists messages (
  id          text primary key,
  contact_id  text not null references contacts(id),
  direction   text not null,               -- in | out
  body        text not null,
  created_at  real not null,
  -- inbound: delivered_to_thread | delivery_failed | pending
  -- outbound: held | sending | sent | delivered (read receipt) | failed | offline_queued
  state       text not null,
  detail      text not null default '',
  thread_id   text,
  tox_ids     text not null default '[]'   -- toxcore message ids for outbound parts
);
create index if not exists messages_contact on messages(contact_id, created_at);
create table if not exists events (
  seq         integer primary key autoincrement,
  at          real not null,
  contact_id  text,
  kind        text not null,
  data        text not null default '{}'
);
create table if not exists kv (k text primary key, v text not null);
"""


class Journal:
    def __init__(self, path=DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._listeners = []
        with self._conn() as c:
            c.executescript(SCHEMA)
            # Older journals made thread_id unique (one guest per thread); rebuild without it.
            ddl = c.execute("select sql from sqlite_master where name='contacts'").fetchone()[0]
            if "thread_id     text unique" in ddl:
                c.executescript("""
                    pragma foreign_keys=off;
                    begin;
                    alter table contacts rename to contacts_old;
                """ + SCHEMA.split("create table if not exists messages")[0] + """
                    insert into contacts select * from contacts_old;
                    drop table contacts_old;
                    commit;
                    pragma foreign_keys=on;
                """)
            cols = {r[1] for r in c.execute("pragma table_info(messages)")}
            if "shown_at" not in cols:
                # When the guest could first see the message: arrival for theirs, Tox send for ours.
                c.execute("alter table messages add column shown_at real")
            cols = {r[1] for r in c.execute("pragma table_info(contacts)")}
            if "role" not in cols:
                # Who is on the other end: person (a human guest), agent (someone's agent asking
                # ours), consult (an agent ours questions on the owner's behalf).
                c.execute("alter table contacts add column role text not null default 'person'")
            cols = {r[1] for r in c.execute("pragma table_info(contacts)")}
            if "tier" not in cols:
                # story: the curated material (new contacts); deep: the full archive. Contacts that
                # existed before tiers keep the access they had, which was the single (deep) library.
                c.execute("alter table contacts add column tier text not null default 'story'")
                c.execute("update contacts set tier='deep'")
            cols = {r[1] for r in c.execute("pragma table_info(messages)")}
            if "origin" not in cols:
                # Who wrote an outbound message: agent (tox-send) or owner (viewer/API).
                c.execute("alter table messages add column origin text not null default 'agent'")

    def _conn(self):
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("pragma journal_mode=wal")
            c.execute("pragma busy_timeout=30000")
            self._local.c = c
        return c

    # --- change feed -------------------------------------------------------
    def subscribe(self, fn):
        self._listeners.append(fn)
        return lambda: self._listeners.remove(fn)

    def event(self, kind, contact_id=None, **data):
        with self._lock:
            c = self._conn()
            cur = c.execute("insert into events(at, contact_id, kind, data) values (?,?,?,?)",
                            (time.time(), contact_id, kind, json.dumps(data)))
            seq = cur.lastrowid
        ev = {"seq": seq, "at": time.time(), "contact_id": contact_id, "kind": kind, "data": data}
        for fn in list(self._listeners):
            try:
                fn(ev)
            except Exception:
                pass
        return ev

    def events_since(self, seq, limit=500):
        rows = self._conn().execute("select * from events where seq > ? order by seq limit ?", (seq, limit))
        return [{"seq": r["seq"], "at": r["at"], "contact_id": r["contact_id"], "kind": r["kind"],
                 "data": json.loads(r["data"])} for r in rows]

    def last_seq(self):
        r = self._conn().execute("select max(seq) from events").fetchone()
        return r[0] or 0

    # --- kv ----------------------------------------------------------------
    def get(self, k, default=None):
        r = self._conn().execute("select v from kv where k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def put(self, k, v):
        self._conn().execute("insert into kv(k,v) values(?,?) on conflict(k) do update set v=excluded.v",
                             (k, json.dumps(v)))

    # --- contacts ----------------------------------------------------------
    def contacts(self, include_archived=False):
        q = "select * from contacts" + ("" if include_archived else " where status not in ('archived','blocked')")
        return [dict(r) for r in self._conn().execute(q + " order by created_at")]

    def contact(self, cid):
        r = self._conn().execute("select * from contacts where id=?", (cid,)).fetchone()
        return dict(r) if r else None

    def contact_by_key(self, public_key):
        r = self._conn().execute("select * from contacts where public_key=?", (public_key.upper(),)).fetchone()
        return dict(r) if r else None

    def contacts_by_thread(self, thread_id, include_archived=False):
        q = "select * from contacts where thread_id=?" + ("" if include_archived else " and status not in ('archived','blocked')")
        return [dict(r) for r in self._conn().execute(q + " order by created_at", (thread_id,))]

    def contact_by_thread(self, thread_id):
        r = self._conn().execute("select * from contacts where thread_id=?", (thread_id,)).fetchone()
        return dict(r) if r else None

    def add_contact(self, cid, name, public_key, tox_id=None, notes="", kind="tox", role="person", tier="story"):
        now = time.time()
        with self._lock:
            self._conn().execute(
                "insert into contacts(id,name,public_key,tox_id,kind,notes,role,tier,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?)",
                (cid, name, public_key.upper(), tox_id.upper() if tox_id else None, kind, notes, role, tier, now, now))
        self.event("contact_added", cid, name=name)
        return self.contact(cid)

    def update_contact(self, cid, **fields):
        if not fields:
            return self.contact(cid)
        fields["updated_at"] = time.time()
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn().execute(f"update contacts set {sets} where id=?", (*fields.values(), cid))
        self.event("contact_updated", cid, **{k: v for k, v in fields.items() if k != "updated_at"})
        return self.contact(cid)

    def delete_contact(self, cid):
        with self._lock:
            self._conn().execute("delete from messages where contact_id=?", (cid,))
            self._conn().execute("delete from contacts where id=?", (cid,))
        self.event("contact_deleted", cid)

    # --- messages ----------------------------------------------------------
    def add_message(self, contact_id, direction, body, state, thread_id=None, detail="", origin="agent"):
        mid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock:
            self._conn().execute(
                "insert into messages(id,contact_id,direction,body,created_at,state,detail,thread_id,shown_at,origin) values (?,?,?,?,?,?,?,?,?,?)",
                (mid, contact_id, direction, body, now, state, detail, thread_id, now if direction == "in" else None,
                 "owner" if origin == "owner" else "agent"))
        self.event("message", contact_id, id=mid, direction=direction, state=state)
        return self.message(mid)

    def message(self, mid):
        r = self._conn().execute("select * from messages where id=?", (mid,)).fetchone()
        return _msg(r) if r else None

    def set_message(self, mid, **fields):
        if fields.get("state") == "sent":
            r = self._conn().execute("select shown_at from messages where id=?", (mid,)).fetchone()
            if r is not None and r[0] is None:
                fields["shown_at"] = time.time()
        if "tox_ids" in fields:
            fields["tox_ids"] = json.dumps(fields["tox_ids"])
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn().execute(f"update messages set {sets} where id=?", (*fields.values(), mid))
        m = self.message(mid)
        self.event("message", m["contact_id"], id=mid, direction=m["direction"], state=m["state"])
        return m

    def messages(self, contact_id, limit=1000):
        rows = self._conn().execute(
            "select * from (select * from messages where contact_id=? "
            "order by coalesce(shown_at, created_at) desc limit ?) order by coalesce(shown_at, created_at)",
            (contact_id, limit))
        return [_msg(r) for r in rows]

    def contact_stats(self, since):
        """One pass over the journal for the overview: per contact, what's waiting on the owner,
        today's activity, and whether they've ever been reachable."""
        rows = self._conn().execute(
            "select contact_id,"
            " sum(direction='out' and state='held') held,"
            " sum((direction='out' and state='failed') or (direction='in' and state='delivery_failed')) stuck,"
            " sum(created_at > ?) today,"
            " sum(direction='in') + sum(state='delivered') reached"
            " from messages group by contact_id", (since,))
        return {r["contact_id"]: dict(r) for r in rows}

    def count_out_since(self, contact_id, since):
        """The agent's messages to a contact since a time that went out or are on their way."""
        r = self._conn().execute(
            "select count(*) from messages where contact_id=? and direction='out' and created_at>? "
            "and origin='agent' and state in ('sending','sent','delivered','offline_queued')",
            (contact_id, since)).fetchone()
        return r[0]

    def messages_in_state(self, direction, states):
        q = f"select * from messages where direction=? and state in ({','.join('?' * len(states))}) order by created_at"
        return [_msg(r) for r in self._conn().execute(q, (direction, *states))]

    def unread_counts(self):
        """Inbound messages newer than the owner's last view of each chat."""
        seen = self.get("seen", {})
        out = {}
        for r in self._conn().execute("select contact_id, created_at from messages where direction='in'"):
            if r["created_at"] > seen.get(r["contact_id"], 0):
                out[r["contact_id"]] = out.get(r["contact_id"], 0) + 1
        return out

    def mark_seen(self, contact_id):
        seen = self.get("seen", {})
        seen[contact_id] = time.time()
        self.put("seen", seen)


def _msg(r):
    d = dict(r)
    d["tox_ids"] = json.loads(d["tox_ids"] or "[]")
    return d
