"""End-to-end self test for toxcore.py: two real Tox nodes befriend each other and chat.

Usage: python selftest.py [--no-internet] [--dht-timeout 30] [--keep]
Exit code 0 = PASS.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toxcore  # noqa: E402
from toxcore import CONNECTION_NAMES, ToxNode, iterate_all, split_message  # noqa: E402

UNICODE_MSG = "Hello B 👋\nline two: naïve café — Ünïcödé ✓\nline three: 日本語テキスト, emoji 🐱‍👤 and RTL שלום\n"
LONG_MSG = ("Long message section %03d: the quick brown fox jumps over the lazy dog. Ωμέγα ☃ 🚀\n" * 60) % tuple(range(60))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-internet", action="store_true", help="skip public bootstrap (LAN discovery only)")
    ap.add_argument("--dht-timeout", type=float, default=30.0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--keep", action="store_true", help="keep the temp savedata dir")
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.v else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # split helper sanity
    chunks = split_message(LONG_MSG)
    assert "".join(chunks) == LONG_MSG
    assert all(len(c.encode()) <= toxcore.TOX_MAX_MESSAGE_LENGTH for c in chunks)
    assert len(LONG_MSG.encode()) > toxcore.TOX_MAX_MESSAGE_LENGTH
    print(f"libtoxcore {toxcore.version()}  long message = {len(LONG_MSG.encode())} bytes -> {len(chunks)} chunks")

    tmp = Path(tempfile.mkdtemp(prefix="tox-selftest-"))
    t0 = time.monotonic()
    ts = lambda: f"{time.monotonic() - t0:6.2f}s"  # noqa: E731
    ok = False
    a = b = None
    try:
        a = ToxNode(tmp / "a.tox", "selftest-A", status_message="I am A")
        b = ToxNode(tmp / "b.tox", "selftest-B", status_message="I am B")
        print(f"[{ts()}] A id={a.address}  udp_port={a.udp_port}")
        print(f"[{ts()}] B id={b.address}  udp_port={b.udp_port}")

        ev = {"a_dht": None, "b_dht": None, "req": None, "a_conn": None, "b_conn": None,
              "a_name": None}
        b_inbox: list[str] = []
        receipts: set[int] = set()

        def mk_self(tag):
            def f(status):
                print(f"[{ts()}] {tag} self connection -> {CONNECTION_NAMES[status]}")
                if status and ev[tag + "_dht"] is None:
                    ev[tag + "_dht"] = time.monotonic() - t0
            return f
        a.on_self_connection = mk_self("a")
        b.on_self_connection = mk_self("b")

        def b_req(pk, msg):
            ev["req"] = time.monotonic() - t0
            print(f"[{ts()}] B got friend request from {pk[:16]}... msg={msg!r}")
            return True  # accept
        b.on_friend_request = b_req

        def mk_fconn(tag):
            def f(fn, status):
                print(f"[{ts()}] {tag} friend {fn} connection -> {CONNECTION_NAMES[status]}")
                if status and ev[tag + "_conn"] is None:
                    ev[tag + "_conn"] = time.monotonic() - t0
            return f
        a.on_friend_connection = mk_fconn("a")
        b.on_friend_connection = mk_fconn("b")
        a.on_friend_name = lambda fn, name: ev.__setitem__("a_name", name)
        b.on_friend_message = lambda fn, text, t: b_inbox.append(text)
        a.on_read_receipt = lambda fn, mid: receipts.add(mid)
        b_typing: list[bool] = []
        b.on_friend_typing = lambda fn, typing: b_typing.append(typing)

        if not args.no_internet:
            na, nb = a.bootstrap_public(), b.bootstrap_public()
            print(f"[{ts()}] bootstrapped A on {na} nodes, B on {nb} nodes (+TCP relays)")
        # Direct local bootstrap A -> B (equivalent to LAN discovery, but deterministic)
        a.bootstrap("127.0.0.1", b.udp_port, b.address[:64])
        b.bootstrap("127.0.0.1", a.udp_port, a.address[:64])

        fa = a.friend_add(b.address, "selftest: please accept")
        print(f"[{ts()}] A sent friend request (friend #{fa})")

        if not iterate_all([a, b], lambda: ev["a_conn"] and ev["b_conn"], args.timeout):
            print("FAIL: friends did not connect", ev)
            return 1
        fb = b.friend_by_public_key(a.public_key)
        assert fb is not None and b.friend_public_key(fb) == a.public_key
        assert b.friend_list() == [fb] and a.friend_list() == [fa]
        print(f"[{ts()}] connected. A sees B as {CONNECTION_NAMES[a.friend_connection_status(fa)]}")

        a.set_typing(fa, True)
        iterate_all([a, b], lambda: True in b_typing, 10)
        assert True in b_typing, "typing not received"
        a.set_typing(fa, False)

        t_send = time.monotonic()
        ids = a.send_message(fa, UNICODE_MSG) + a.send_message(fa, LONG_MSG)
        print(f"[{ts()}] A sent {len(ids)} messages, ids={ids}")
        expected = split_message(UNICODE_MSG) + split_message(LONG_MSG)
        if not iterate_all([a, b], lambda: len(b_inbox) >= len(expected) and receipts >= set(ids), 60):
            print(f"FAIL: B got {len(b_inbox)}/{len(expected)}, receipts {sorted(receipts)} of {ids}")
            return 1
        t_done = time.monotonic() - t_send
        assert b_inbox == expected, "content mismatch"
        assert b_inbox[0] == UNICODE_MSG and "".join(b_inbox[1:]) == LONG_MSG
        print(f"[{ts()}] B received all {len(b_inbox)} messages intact; A got {len(receipts)} read receipts "
              f"({t_done*1000:.0f} ms send->all receipts)")
        print(f"[{ts()}] typing events seen by B: {b_typing}; A sees B's name: {a.friend_name(fa)!r}; "
              f"status msg: {a.friend_status_message(fa)!r}")

        # savedata round trip: reload A and check identity + friend persisted
        addr, a_dir = a.address, a.savedata_path
        a.kill()
        a = ToxNode(a_dir, "selftest-A")
        assert a.address == addr and a.friend_by_public_key(b.public_key) == fa
        print(f"[{ts()}] savedata reload OK (same Tox ID, friend persisted)")

        # public DHT reachability
        if not args.no_internet:
            iterate_all([a, b], lambda: ev["a_dht"] and ev["b_dht"], args.dht_timeout)
            iterate_all([a], lambda: a.get_connection_status() != 0, args.dht_timeout)
            sa, sb = a.get_connection_status(), b.get_connection_status()
            print(f"[{ts()}] public DHT: A(reloaded)={CONNECTION_NAMES[sa]} B={CONNECTION_NAMES[sb]} "
                  f"(B first DHT connect at {ev['b_dht'] and round(ev['b_dht'], 2)}s)")
            if not (sb and sa):
                print("FAIL: did not reach public DHT")
                return 1

        print("TIMINGS:", {k: (round(v, 2) if v else v) for k, v in ev.items() if k != "a_name"})
        ok = True
        print("SELFTEST PASS")
        return 0
    finally:
        for n in (a, b):
            if n is not None:
                n.kill()
        if args.keep or not ok:
            print("savedata dir:", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
