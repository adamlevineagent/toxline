"""A scriptable Tox peer that plays a guest over the real Tox network.

  python tools/tox_peer.py --profile w1 --id                     print this peer's Tox ID
  python tools/tox_peer.py --profile w1 --add <AGENT_TOX_ID>     send a friend request
  python tools/tox_peer.py --profile w1 --say "hello" --wait 90  send, then print replies
  python tools/tox_peer.py --profile w1 --listen 300             just print incoming messages

Profiles live in tools/peers/<name>.tox so the identity is stable across runs.
Prints one JSON line per event so test agents can parse it.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tox"))
import toxcore  # noqa: E402


def out(kind, **kw):
    print(json.dumps({"t": round(time.time() - T0, 2), "event": kind, **kw}, ensure_ascii=False), flush=True)


T0 = time.time()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="peer")
    ap.add_argument("--name", default=None)
    ap.add_argument("--id", action="store_true")
    ap.add_argument("--add", help="agent Tox ID (76 hex) to friend-request")
    ap.add_argument("--greeting", default="Hi! Testing Toxline.")
    ap.add_argument("--say", action="append", default=[], help="message to send (repeatable)")
    ap.add_argument("--wait", type=float, default=60, help="seconds to keep listening after sending")
    ap.add_argument("--quiet-after", type=float, default=0, help="stop after this many seconds with no new message (once at least one reply arrived)")
    ap.add_argument("--listen", type=float, default=0)
    ap.add_argument("--accept-all", action="store_true", help="accept incoming friend requests")
    args = ap.parse_args()

    pdir = ROOT / "tools" / "peers"
    pdir.mkdir(parents=True, exist_ok=True)
    node = toxcore.ToxNode(pdir / f"{args.profile}.tox", name=args.name or args.profile, auto_accept=args.accept_all)
    if args.id:
        print(node.address)
        node.kill()
        return
    state = {"replies": 0, "last": time.time(), "online": False}

    def on_msg(fn, text, mt):
        state["replies"] += 1
        state["last"] = time.time()
        out("message", text=text)

    node.on_friend_message = on_msg
    def on_conn(fn, st):
        if st != 0:
            state["online"] = True
            state["friend"] = fn
        out("friend_connection", friend=fn, status=st)
    node.on_friend_connection = on_conn
    node.on_read_receipt = lambda fn, mid: out("receipt", id=mid)
    node.on_friend_typing = lambda fn, on: out("typing", on=on)
    node.on_self_connection = lambda st: out("self_connection", status=st)
    node.on_friend_request = lambda pk, m: out("friend_request", public_key=pk, message=m)
    node.bootstrap_public()
    out("ready", tox_id=node.address)

    if args.add:
        fn = node.friend_by_public_key(args.add[:64])
        if fn is None:
            node.friend_add(args.add, args.greeting)
            out("friend_request_sent")
        else:
            out("already_friends")

    def friend():
        return state.get("friend")

    if args.say:
        ok = node.run(until=lambda: state["online"], timeout=180)
        if not ok:
            out("error", message="agent never came online")
            node.kill()
            sys.exit(2)
        for s in args.say:
            ids = node.send_message(friend(), s)
            out("sent", text=s, ids=ids)
            node.run(timeout=0.5)
        start = time.time()

        def done():
            if time.time() - start > args.wait:
                return True
            return args.quiet_after and state["replies"] and time.time() - state["last"] > args.quiet_after
        node.run(until=done)
    elif args.listen:
        node.run(timeout=args.listen)
    out("done", replies=state["replies"])
    node.kill()


if __name__ == "__main__":
    main()
