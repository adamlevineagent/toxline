"""tox-send / toxline CLI. The agent's only way to put words in a guest's chat.

The guest is found from the thread the agent is running in (CODEX_THREAD_ID),
so the agent never names a recipient and can't message the wrong person.

  tox-send "message text"          send to this thread's guest
  tox-send --file reply.md         send a file's contents
  echo text | tox-send -           read the message from stdin
  tox-send --who                   show who this thread talks to + recent chat
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

PORT = int(os.environ.get("TOXLINE_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"

STATE_TEXT = {
    "delivered": "DELIVERED - their client confirmed receipt",
    "sent": "SENT - handed to Tox; waiting for their client's receipt",
    "offline_queued": "QUEUED - they are offline; it will go out automatically when they connect",
    "held": "HELD - the owner has outgoing messages on hold; it will go out when they release it",
    "failed": "FAILED",
    "sending": "SENDING",
}


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("error")
        except Exception:
            msg = str(e)
        sys.exit(f"tox-send: {msg}")
    except urllib.error.URLError:
        sys.exit("tox-send: the toxline service is not running (start it with toxline.cmd)")


def thread_id(args):
    tid = args.thread or os.environ.get("CODEX_THREAD_ID")
    if not tid:
        sys.exit("tox-send: no CODEX_THREAD_ID in this environment; pass --thread <id>")
    return tid


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tox-send", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="*", help="message text ('-' reads stdin)")
    ap.add_argument("--file", help="send the contents of this UTF-8 file")
    ap.add_argument("--who", action="store_true", help="show this thread's guest and recent chat")
    ap.add_argument("--thread", help="override the thread id (default: CODEX_THREAD_ID)")
    ap.add_argument("--json", action="store_true", help="print the raw result")
    args = ap.parse_args(argv)
    tid = thread_id(args)

    if args.who:
        r = call("GET", f"/api/whoami?thread_id={tid}&limit=15")
        c = r["contact"]
        print(f"This thread talks to {c['name']} (guest id {c['id']}, Tox {c['online']}, "
              f"status {c['status']}{', OUTGOING ON HOLD' if c['hold_outgoing'] else ''}).")
        for m in r["recent"]:
            who = c["name"] if m["direction"] == "in" else "you"
            print(f"  [{who}] {m['body'][:300]}" + (f"   ({m['state']})" if m["direction"] == "out" else ""))
        return 0

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            body = f.read()
    elif args.text == ["-"] or (not args.text and not sys.stdin.isatty()):
        body = sys.stdin.buffer.read().decode("utf-8")
    else:
        body = " ".join(args.text)
    if not body.strip():
        ap.error("nothing to send")

    r = call("POST", "/api/send", {"thread_id": tid, "body": body, "wait": 4})
    if args.json:
        print(json.dumps(r, indent=2))
        return 0
    m = r["message"]
    state = STATE_TEXT.get(m["state"], m["state"].upper())
    print(f"To {r['to']['name']}: {state}" + (f" ({m['detail']})" if m["detail"] and m["state"] == "failed" else ""))
    print(f"message id {m['id']}, {len(m['body'])} chars")
    return 0 if m["state"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
