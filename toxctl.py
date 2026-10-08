"""toxctl: run Toxline from a terminal (or let an AI assistant run it for you).

The viewer's everyday controls, as commands. Contacts can be named by id or by name.

  python toxctl.py status                     service, Tox network, Codex Desktop, contacts, requests
  python toxctl.py start                      start the service if it isn't running
  python toxctl.py chat NAME [--last N]       the chat as the other side sees it
  python toxctl.py thread NAME [--turns N]    what the agent did privately in its thread
  python toxctl.py wait NAME [--after MSG]    block until something new happens in that chat
  python toxctl.py tell NAME "text"           message the agent privately in its thread (--file F)
  python toxctl.py send NAME "text"           message the contact directly, as yourself (--file F)
  python toxctl.py add NAME --role ROLE ...   new contact; see `add -h`
  python toxctl.py accept REQUEST --name N    set up a pending friend request as a contact
  python toxctl.py held [NAME]                outgoing messages waiting for you
  python toxctl.py release MSG [--file F]     send a held message (optionally edited)
  python toxctl.py discard MSG                drop a held message
  python toxctl.py hold NAME on|off           hold every outgoing message for review
  python toxctl.py pause|resume|archive|unarchive NAME
  python toxctl.py notes NAME "text"          what the agent knows about them (or the mission)
  python toxctl.py role NAME person|agent|consult    who's on the other end
  python toxctl.py rename NAME "New name"
  python toxctl.py redeliver MSG              retry delivering an incoming message to the agent
  python toxctl.py dismiss REQUEST            ignore a pending friend request
  python toxctl.py settings [key=value ...]   show or change settings
  python toxctl.py open NAME                  open the agent's thread in Codex Desktop
  python toxctl.py id                         this Toxline's Tox ID (give it to people)

Add --json to most commands for machine-readable output. TOXLINE_PORT picks the port (default 8765).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("TOXLINE_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"
ROLES = {"person": "a person", "agent": "someone's agent (it asks, yours answers)",
         "consult": "an agent yours is questioning for you"}


class Down(Exception):
    pass


def call(method, path, payload=None, timeout=150):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = str(e)
        sys.exit(f"toxctl: {msg}")
    except urllib.error.URLError:
        raise Down()


def state():
    try:
        return call("GET", "/api/state", timeout=10)
    except Down:
        sys.exit(f"toxctl: Toxline isn't running on port {PORT}. Start it: python toxctl.py start "
                 f"(or double-click Start-Toxline.cmd)")


def find(snap, who):
    w = who.strip().lower()
    cs = snap["contacts"]
    for test in (lambda c: c["id"].lower() == w, lambda c: c["name"].lower() == w,
                 lambda c: c["name"].lower().startswith(w), lambda c: w in c["name"].lower()):
        hits = [c for c in cs if test(c)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            sys.exit(f"toxctl: {who!r} matches several contacts: " + ", ".join(f"{c['name']} ({c['id']})" for c in hits))
    sys.exit(f"toxctl: no contact {who!r}. Contacts: " + (", ".join(f"{c['name']} ({c['id']})" for c in cs) or "none"))


def text_arg(a):
    if getattr(a, "file", None):
        return Path(a.file).read_text(encoding="utf-8")
    t = " ".join(a.text or [])
    if t == "-" or (not t and not sys.stdin.isatty()):
        return sys.stdin.buffer.read().decode("utf-8")
    return t


def ago(t):
    s = time.time() - t
    return "now" if s < 60 else f"{int(s // 60)}m ago" if s < 3600 else f"{int(s // 3600)}h ago" if s < 86400 else f"{int(s // 86400)}d ago"


def out(obj, a, human):
    if getattr(a, "json", False):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        human(obj)


# ------------------------------------------------------------------ commands
def cmd_status(a):
    s = state()

    def show(s):
        me = s["self"]
        print(f"Toxline on port {PORT}: running")
        print(f"  Tox network: {me['connection']}" + ("  (joining; usually under a minute)" if me["connection"] == "none" else ""))
        print(f"  Tox ID: {me['tox_id']}")
        print(f"  Agent name: {me['name']}")
        print(f"  Delivery: {s['ingress']}")
        if "not found" in (s["ingress"] or ""):
            print("  ! Codex Desktop isn't open: messages still reach agents in the background, but open it to watch threads live.")
        print(f"Contacts ({len([c for c in s['contacts'] if c['status'] != 'archived'])} active):")
        for c in s["contacts"]:
            if c["status"] == "archived" and not a.all:
                continue
            flags = [ROLES.get(c.get("role") or "person", c.get("role")), c["status"]]
            if c["online"] != "none":
                flags.append("online")
            elif not c.get("last") or not c.get("ever_online"):
                flags.append("not connected yet (friend request not accepted, or they haven't come online)")
            else:
                flags.append("offline")
            if c["hold_outgoing"]:
                flags.append("holding outgoing")
            if c.get("budget"):
                flags.append(f"budget {c['budget']['used']}/{c['budget']['limit']}")
            if c.get("unread"):
                flags.append(f"{c['unread']} unread in the viewer")
            last = c.get("last")
            lastt = f"last: {'agent' if last['direction'] == 'out' else 'them'}, {ago(last['created_at'])}" if last else "no messages"
            print(f"  - {c['name']} [{c['id']}]: {', '.join(flags)}; {lastt}")
        if s["requests"]:
            print("Pending friend requests (set up with: toxctl accept KEY --name NAME):")
            for r in s["requests"]:
                kind = "AGENT" if r.get("agent") else "person?"
                print(f"  - {r['public_key'][:16]}  ({kind}, {ago(r['at'])}) {r.get('greeting') or ''}")
    out(s, a, show)


def cmd_start(a):
    try:
        call("GET", "/api/state", timeout=5)
        print("Toxline is already running.")
        return
    except Down:
        pass
    log = ROOT / "state" / "toxline.log"
    log.parent.mkdir(exist_ok=True)
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, "-X", "utf8", str(ROOT / "toxlined.py"), "--ingress",
                      os.environ.get("TOXLINE_INGRESS", "desktop"), "--port", str(PORT)],
                     cwd=ROOT, stdout=open(log, "a", encoding="utf-8"), stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, creationflags=flags,
                     env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    for _ in range(90):
        time.sleep(1)
        try:
            call("GET", "/api/state", timeout=3)
            print(f"Toxline started on port {PORT} (viewer: {BASE}/, log: {log}).")
            for _ in range(60):
                if call("GET", "/api/state", timeout=5)["self"]["connection"] != "none":
                    print("It's on the Tox network.")
                    return
                time.sleep(1)
            print("Not on the Tox network yet after a minute: check the firewall allows Python (see docs/TROUBLESHOOTING.md).")
            return
        except Down:
            pass
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
    sys.exit("toxctl: Toxline didn't start. Last log lines:\n" + "\n".join(tail))


def cmd_id(a):
    print(state()["self"]["tox_id"])


def render_chat(c, msgs):
    print(f"Chat with {c['name']} [{c['id']}] ({ROLES.get(c.get('role') or 'person')}). "
          f"'them' is {c['name']}; 'agent' is your agent.")
    for m in msgs:
        who = "them " if m["direction"] == "in" else "agent" if m.get("origin") != "owner" else "you  "
        t = time.strftime("%m-%d %H:%M", time.localtime(m.get("shown_at") or m["created_at"]))
        note = ""
        if m["direction"] == "out" and m["state"] not in ("sent", "delivered"):
            d = m["detail"] if m["detail"] and not m["detail"].startswith(m["state"]) else m["detail"][len(m["state"]) + 2:] if m["detail"] else ""
            note = f"  [{m['state']}{': ' + d if d else ''}; id {m['id']}]"
        if m["direction"] == "out" and m["state"] in ("sent", "delivered"):
            note = "  ✓✓ delivered" if m["state"] == "delivered" else "  ✓ sent"
        if m["direction"] == "in" and m["state"] not in ("delivered_to_thread",):
            note = f"  [{m['state']}; id {m['id']}]"
        print(f"\n--- {t} {who}{note}\n{m['body']}")


def cmd_chat(a):
    c = find(state(), a.name)
    msgs = call("GET", f"/api/contacts/{c['id']}/messages?limit={a.last}")["messages"]
    out(msgs, a, lambda m: render_chat(c, m))


def cmd_thread(a):
    c = find(state(), a.name)
    r = call("GET", f"/api/contacts/{c['id']}/thread?turns={a.turns}")
    if a.wait:
        # Let the agent finish what it's doing (e.g. writing its report) before reading.
        deadline = time.time() + a.wait
        while r["turns"] and r["turns"][-1].get("status") == "inProgress" and time.time() < deadline:
            time.sleep(10)
            r = call("GET", f"/api/contacts/{c['id']}/thread?turns={a.turns}")

    def show(r):
        print(f"Agent thread {r['thread_id']} for {c['name']} (last {a.turns} turns, oldest first):")
        for t in r["turns"]:
            print(f"\n=== turn {t.get('status')}")
            for i in t["items"]:
                if i["type"] == "agentMessage":
                    print(f"agent: {i.get('text', '')}")
                elif i["type"] == "userMessage":
                    print(f"in: {i.get('text', '')[:1500]}")
                elif i["type"] == "commandExecution" and a.commands:
                    print(f"  ran: {(i.get('command') or '')[:300]}")
                elif i["type"] == "fileChange" and a.commands:
                    print(f"  changed: {', '.join(i.get('files') or [])}")
        if not r["turns"]:
            print("(nothing readable: Codex Desktop may be closed)")
        elif r["turns"][-1].get("status") == "inProgress":
            print("\n(the agent is still working on this turn; add --wait 300 to wait for it to finish)")
    out(r, a, show)


def cmd_wait(a):
    c = find(state(), a.name)
    first = call("GET", f"/api/contacts/{c['id']}/messages?limit=500")["messages"]
    if a.after:
        ids = [m["id"] for m in first]
        if a.after not in ids:
            sys.exit(f"toxctl: no message {a.after} in {c['name']}'s chat")
        first = first[:ids.index(a.after) + 1]   # anything after it counts as new, even if it already came
    seen = {m["id"] for m in first}
    held0 = {m["id"] for m in first if m["state"] == "held"}
    deadline = time.time() + a.timeout
    while time.time() < deadline:
        time.sleep(3)
        now = call("GET", f"/api/contacts/{c['id']}/messages?limit=500")["messages"]
        # New messages either way, or an existing one that just got held for you.
        new = [m for m in now if m["id"] not in seen or (m["state"] == "held" and m["id"] not in held0)]
        if new:
            def show(ms):
                render_chat(c, ms)
                print(f"\n(latest message {now[-1]['id']}: to wait for what comes next, "
                      f"run: toxctl wait {c['id']} --after {now[-1]['id']})")
            out(new, a, show)
            return
    last = first[-1]["id"] if first else None
    print(f"No new messages from or to {c['name']} in {a.timeout}s."
          + (f" Keep waiting with: toxctl wait {c['id']} --after {last}" if last else ""))
    sys.exit(3)


def cmd_tell(a):
    c = find(state(), a.name)
    body = text_arg(a)
    if not body.strip():
        sys.exit("toxctl: nothing to tell")
    r = call("POST", f"/api/contacts/{c['id']}/tell", {"body": body})
    out(r, a, lambda r: print(f"Told the agent in {c['name']}'s thread ({r.get('detail') or r.get('state')})."
                              if r.get("ok") else f"Not delivered yet: {r.get('state')} ({r.get('detail')})"))


def cmd_send(a):
    c = find(state(), a.name)
    body = text_arg(a)
    r = call("POST", "/api/send", {"contact_id": c["id"], "body": body, "origin": "owner"})
    out(r, a, lambda r: print(f"To {c['name']}: {r['message']['state']} (id {r['message']['id']})"))


def cmd_add(a):
    if a.role != "person" and not a.tox_id and not a.test:
        sys.exit("toxctl: an agent contact needs --tox-id (the Tox ID at the top-left of their Toxline)")
    body = {"name": a.name, "role": a.role, "tox_id": a.tox_id or "", "kind": "test" if a.test else "tox",
            "thread": a.thread, "notes": "\n\n".join(x for x in (a.mission, a.notes) if x), "greeting": a.greeting or ""}
    if a.test:
        body.pop("tox_id")
    c = call("POST", "/api/contacts", body, timeout=200)
    out(c, a, lambda c: print(f"Added {c['name']} [{c['id']}] as {ROLES[c['role']]}; agent thread {c['thread_id']}."
                              + (" Your agent opens the conversation once they accept and come online."
                                 if c["role"] == "consult" and c["notes"] else "")))


def cmd_accept(a):
    s = state()
    hits = [r for r in s["requests"] if r["public_key"].lower().startswith(a.request.lower())]
    if len(hits) != 1:
        sys.exit("toxctl: no single pending request matches that; see `toxctl status`")
    r = hits[0]
    role = a.role or (r.get("role") or ("agent" if r.get("agent") else "person"))
    c = call("POST", "/api/contacts", {"name": a.name or r.get("returning") or "Guest", "tox_id": r["public_key"],
                                       "role": role, "thread": a.thread or r.get("thread_id") or "new",
                                       "notes": a.notes or ""}, timeout=200)
    out(c, a, lambda c: print(f"Set up {c['name']} [{c['id']}] as {ROLES[c['role']]}; agent thread {c['thread_id']}."))


def cmd_held(a):
    s = state()
    cs = [find(s, a.name)] if a.name else [c for c in s["contacts"] if c["status"] != "archived"]
    rows = []
    for c in cs:
        for m in call("GET", f"/api/contacts/{c['id']}/messages?limit=500")["messages"]:
            if m["direction"] == "out" and m["state"] in ("held", "failed", "offline_queued"):
                rows.append(dict(m, contact=c["name"]))

    def show(rows):
        if not rows:
            print("Nothing waiting.")
        for m in rows:
            print(f"\n--- {m['id']} to {m['contact']}: {m['state']} ({m['detail']})\n{m['body']}")
    out(rows, a, show)


def cmd_release(a):
    body = Path(a.file).read_text(encoding="utf-8") if a.file else None
    m = call("POST", f"/api/messages/{a.msg}/release", {"body": body} if body is not None else {})
    out(m, a, lambda m: print(f"{m['id']}: {m['state']}" + (f" ({m['detail']})" if m["state"] == "held" else "")))


def cmd_discard(a):
    m = call("POST", f"/api/messages/{a.msg}/discard")
    print(f"{m['id']}: {m['state']}")


def update(a, **fields):
    c = find(state(), a.name)
    r = call("POST", f"/api/contacts/{c['id']}/update", fields)
    print(f"{r['name']}: status {r['status']}, holding outgoing {'on' if r['hold_outgoing'] else 'off'}, role {r.get('role')}")


def cmd_hold(a):
    update(a, hold_outgoing=a.state == "on")


def cmd_settings(a):
    if a.pairs:
        known = call("GET", "/api/settings")
        bad = [p for p in a.pairs if "=" not in p or p.split("=", 1)[0] not in known]
        if bad:
            sys.exit(f"toxctl: settings take key=value with these keys: {', '.join(known)} (got {', '.join(bad)})")
        changes = dict(p.split("=", 1) for p in a.pairs)
        cfg = call("POST", "/api/settings", changes)
        if not a.json:
            for k in changes:
                print(f"Set {k} = {cfg[k]}")
            return
    else:
        cfg = call("GET", "/api/settings")
    out(cfg, a, lambda cfg: [print(f"{k} = {v}") for k, v in cfg.items()])


def cmd_redeliver(a):
    m = call("POST", f"/api/messages/{a.msg}/redeliver")
    print(f"{m['id']}: {m['state']}")


def cmd_dismiss(a):
    hits = [r for r in state()["requests"] if r["public_key"].lower().startswith(a.request.lower())]
    if len(hits) != 1:
        sys.exit("toxctl: no single pending request matches that; see `toxctl status`")
    call("POST", f"/api/requests/{hits[0]['public_key']}/dismiss")
    print("Dismissed.")


def cmd_open(a):
    c = find(state(), a.name)
    print(call("POST", f"/api/contacts/{c['id']}/open").get("note", "opened"))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="toxctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name, fn, help, json_flag=True):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(fn=fn)
        if json_flag:
            sp.add_argument("--json", action="store_true", help="machine-readable output")
        return sp

    sp = p("status", cmd_status, "service, network, contacts, requests"); sp.add_argument("--all", action="store_true", help="include archived")
    p("start", cmd_start, "start the service if needed", False)
    p("id", cmd_id, "print this Toxline's Tox ID", False)
    sp = p("chat", cmd_chat, "show a chat"); sp.add_argument("name"); sp.add_argument("--last", type=int, default=40)
    sp = p("thread", cmd_thread, "show the agent's private thread"); sp.add_argument("name"); sp.add_argument("--turns", type=int, default=5, help="1-10")
    sp.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="if the agent is mid-turn, wait up to this long for it to finish")
    sp.add_argument("--commands", action="store_true", help="also list the commands it ran and files it changed")
    sp = p("wait", cmd_wait, "wait for chat activity"); sp.add_argument("name"); sp.add_argument("--timeout", type=int, default=600)
    sp.add_argument("--after", help="message id to wait after (from the previous output), so nothing in between is missed")
    for name, fn, h in (("tell", cmd_tell, "message the agent privately"), ("send", cmd_send, "message the contact as yourself")):
        sp = p(name, fn, h); sp.add_argument("name"); sp.add_argument("text", nargs="*"); sp.add_argument("--file")
    sp = p("add", cmd_add, "add a contact")
    sp.add_argument("name")
    sp.add_argument("--role", choices=list(ROLES), default="person",
                    help="person: a human in a Tox app; agent: someone's agent asks yours; consult: yours questions theirs")
    sp.add_argument("--tox-id", help="their 76-character Tox ID (people: from their Tox app; agents: top-left of their Toxline)")
    sp.add_argument("--mission", help="consult: what your agent should find out (it opens the conversation)")
    sp.add_argument("--notes", help="what your agent should know about them")
    sp.add_argument("--thread", default="new", help="'new' (default) or an existing Codex thread id to bind")
    sp.add_argument("--greeting", help="friend-request message (default from settings)")
    sp.add_argument("--test", action="store_true", help="a simulated contact you type as, from the viewer")
    sp = p("accept", cmd_accept, "set up a pending friend request")
    sp.add_argument("request", help="the start of the request's key, from `status`")
    sp.add_argument("--name"); sp.add_argument("--role", choices=list(ROLES)); sp.add_argument("--notes")
    sp.add_argument("--thread", help="default: a new thread (a returning contact keeps theirs)")
    sp = p("held", cmd_held, "messages waiting for you"); sp.add_argument("name", nargs="?")
    sp = p("release", cmd_release, "send a held message"); sp.add_argument("msg"); sp.add_argument("--file", help="send this text instead")
    sp = p("discard", cmd_discard, "drop a held message", False); sp.add_argument("msg")
    sp = p("hold", cmd_hold, "hold outgoing on/off", False); sp.add_argument("name"); sp.add_argument("state", choices=["on", "off"])
    for name, status in (("pause", "paused"), ("resume", "active"), ("archive", "archived"), ("unarchive", "active")):
        sp = p(name, lambda a, s=status: update(a, status=s), f"{name} a contact", False); sp.add_argument("name")
    sp = p("notes", lambda a: update(a, notes=" ".join(a.text)), "set notes / mission", False)
    sp.add_argument("name"); sp.add_argument("text", nargs="+")
    sp = p("role", lambda a: update(a, role=a.role), "change who's on the other end", False)
    sp.add_argument("name"); sp.add_argument("role", choices=list(ROLES))
    sp = p("rename", lambda a: update(a, name=a.new), "rename a contact", False); sp.add_argument("name"); sp.add_argument("new")
    sp = p("redeliver", cmd_redeliver, "retry delivering an incoming message", False); sp.add_argument("msg")
    sp = p("dismiss", cmd_dismiss, "ignore a pending friend request", False); sp.add_argument("request")
    sp = p("settings", cmd_settings, "show or change settings"); sp.add_argument("pairs", nargs="*", metavar="key=value")
    sp = p("open", cmd_open, "open the agent thread in Codex Desktop", False); sp.add_argument("name")
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except Down:
        sys.exit(f"toxctl: Toxline isn't running on port {PORT}. Start it: python toxctl.py start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
