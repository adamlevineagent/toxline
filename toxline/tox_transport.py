"""Real Tox transport: one Tox identity for the agent, driven on a single thread.

toxcore is not thread-safe, so every call runs on the loop thread; other
threads submit work through _call() and wait for the result.
"""
import queue
import sys
import threading
import time
from pathlib import Path

TOX_DIR = Path(__file__).resolve().parent.parent / "tox"
sys.path.insert(0, str(TOX_DIR))
import toxcore  # noqa: E402

from .transport import Transport  # noqa: E402

CONN = {0: "none", 1: "tcp", 2: "udp"}


class ToxTransport(Transport):
    name = "tox"

    def __init__(self, state_dir, name="Toxline Guide", status_message="Ask me anything"):
        super().__init__()
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.status_message = status_message
        self._q = queue.Queue()
        self._thread = None
        self._stop = False
        self._addr = None
        self.node = None
        self._known_requests = {}
        self._in = {}    # (friend, file) -> incoming transfer: {fh, path, ref, size, got, pk}
        self._out = {}   # (friend, file) -> outgoing transfer: {fh, ref, pk}

    # ----------------------------------------------------------- lifecycle
    def start(self):
        ready = threading.Event()
        err = []

        def boot():
            try:
                self.node = toxcore.ToxNode(self.state_dir / "agent.tox", name=self.name,
                                            status_message=self.status_message)
                n = self.node
                n.on_self_connection = lambda st: self.on_self_connection(CONN.get(st, "none"))
                n.on_friend_request = self._req
                n.on_friend_message = lambda fn, text, mt: self.on_message(self._pk(fn), text)
                n.on_friend_connection = self._conn
                n.on_file_recv = self._file_recv
                n.on_file_recv_chunk = self._file_chunk
                n.on_file_chunk_request = self._file_chunk_request
                n.on_file_recv_control = self._file_control
                n.on_read_receipt = lambda fn, mid: self.on_receipt(self._pk(fn), mid)
                n.on_friend_name = lambda fn, nm: self.on_friend_name(self._pk(fn), nm)
                self._addr = n.address
                n.bootstrap_public()
            except Exception as e:
                err.append(e)
            finally:
                ready.set()
            if not err:
                self._loop()

        self._thread = threading.Thread(target=boot, name="tox", daemon=True)
        self._thread.start()
        ready.wait(30)
        if err:
            raise err[0]

    def _loop(self):
        n = self.node
        last_boot = time.time()
        while not self._stop:
            n.iterate()
            deadline = time.time() + n.iteration_interval() / 1000.0
            while True:
                timeout = deadline - time.time()
                if timeout <= 0:
                    break
                try:
                    fn, box, ev = self._q.get(timeout=timeout)
                except queue.Empty:
                    break
                try:
                    box["r"] = fn()
                except Exception as e:
                    box["e"] = e
                ev.set()
            # Re-bootstrap if we've dropped off the network for a while.
            if n.connection_status == 0 and time.time() - last_boot > 60:
                last_boot = time.time()
                try:
                    n.bootstrap_public()
                except Exception:
                    pass
        n.kill()

    def stop(self):
        if self.node:
            try:
                self._call(self.node.save)
            except Exception:
                pass
        self._stop = True
        if self._thread:
            self._thread.join(5)

    def _call(self, fn, timeout=15):
        if threading.current_thread() is self._thread:
            return fn()
        box, ev = {}, threading.Event()
        self._q.put((fn, box, ev))
        if not ev.wait(timeout):
            raise TimeoutError("tox loop busy")
        if "e" in box:
            raise box["e"]
        return box.get("r")

    # ------------------------------------------------------------- helpers
    def _pk(self, fn):
        return (self.node.friend_public_key(fn) or "").upper()

    def _fn(self, pk):
        return self.node.friend_by_public_key(pk.upper()[:64])

    def _req(self, pk, message):
        self._known_requests[pk.upper()] = message
        self.on_friend_request(pk.upper(), message)
        return None   # never auto-accept; the daemon decides

    # --------------------------------------------------------------- files
    # All of these run on the Tox thread. Transfers die with the friend connection.
    def _conn(self, fn, st):
        if st == 0:
            for key in [k for k in self._in if k[0] == fn]:
                self._finish_in(key, False, "they went offline mid-transfer")
            for key in [k for k in self._out if k[0] == fn]:
                self._finish_out(key, False, "they went offline mid-transfer")
        self.on_connection(self._pk(fn), CONN.get(st, "none"))

    def _file_recv(self, fn, num, kind, size, name):
        pk = self._pk(fn)
        offer = None
        if kind == toxcore.TOX_FILE_KIND_DATA:   # avatars and other kinds are always declined
            try:
                offer = self.on_file_offer(pk, size, name)
            except Exception:
                offer = None
        if not offer:
            self.node.file_control(fn, num, toxcore.TOX_FILE_CONTROL_CANCEL)
            return
        path, ref = offer
        try:
            fh = open(path, "wb")
        except OSError as e:
            self.node.file_control(fn, num, toxcore.TOX_FILE_CONTROL_CANCEL)
            self.on_file_done(pk, ref, False, f"couldn't save it: {e}")
            return
        self._in[(fn, num)] = {"fh": fh, "path": path, "ref": ref, "size": size, "got": 0, "pk": pk}
        self.node.file_control(fn, num, toxcore.TOX_FILE_CONTROL_RESUME)

    def _file_chunk(self, fn, num, pos, data):
        st = self._in.get((fn, num))
        if not st:
            return
        if not data:                      # zero-length chunk: the transfer is complete
            ok = st["got"] == st["size"]
            self._finish_in((fn, num), ok, "" if ok else "incomplete transfer")
            return
        if pos + len(data) > st["size"]:  # never write past what they said they'd send
            self.node.file_control(fn, num, toxcore.TOX_FILE_CONTROL_CANCEL)
            self._finish_in((fn, num), False, "sent more than the announced size")
            return
        st["fh"].seek(pos)
        st["fh"].write(data)
        st["got"] += len(data)

    def _file_chunk_request(self, fn, num, pos, length):
        st = self._out.get((fn, num))
        if not st:
            return
        if length == 0:                   # they have it all
            self._finish_out((fn, num), True, "")
            return
        st["fh"].seek(pos)
        self.node.file_send_chunk(fn, num, pos, st["fh"].read(length))

    def _file_control(self, fn, num, control):
        if control == toxcore.TOX_FILE_CONTROL_CANCEL:
            if (fn, num) in self._in:
                self._finish_in((fn, num), False, "they cancelled it")
            if (fn, num) in self._out:
                self._finish_out((fn, num), False, "they declined or cancelled it")

    def _finish_in(self, key, ok, detail):
        st = self._in.pop(key)
        st["fh"].close()
        if not ok:
            try:
                Path(st["path"]).unlink()
            except OSError:
                pass
        self.on_file_done(st["pk"], st["ref"], ok, detail)

    def _finish_out(self, key, ok, detail):
        st = self._out.pop(key)
        st["fh"].close()
        self.on_file_done(st["pk"], st["ref"], ok, detail)

    def send_file(self, pk, path, ref, name=None):
        path = Path(path)

        def go():
            fn = self._fn(pk)
            if fn is None:
                raise RuntimeError("not a Tox friend yet")
            fh = open(path, "rb")
            try:
                num = self.node.file_send(fn, path.stat().st_size, name or path.name)
            except Exception:
                fh.close()
                raise
            self._out[(fn, num)] = {"fh": fh, "ref": ref, "pk": pk.upper()}
        return self._call(go)

    # ----------------------------------------------------------- interface
    def address(self):
        return self._addr

    def ensure_friend(self, pk):
        def go():
            if self._fn(pk) is None:
                self.node.friend_add_norequest(pk[:64])
                self.node.save()
        return self._call(go)

    def accept_request(self, pk):
        return self.ensure_friend(pk)

    def add_friend(self, ident, greeting=""):
        ident = ident.upper()

        def go():
            if self._fn(ident[:64]) is not None:
                return ident[:64]
            if len(ident) == 76:
                self.node.friend_add(ident, greeting[:900] or "Hi!")
            else:
                self.node.friend_add_norequest(ident[:64])
            self.node.save()
            return ident[:64]
        return self._call(go)

    def remove_friend(self, pk):
        def go():
            fn = self._fn(pk)
            if fn is not None:
                self.node.friend_delete(fn)
                self.node.save()
        return self._call(go)

    def friend_online(self, pk):
        def go():
            fn = self._fn(pk)
            return fn is not None and self.node.friend_connection_status(fn) != 0
        return self._call(go)

    def friend_status(self, pk):
        def go():
            fn = self._fn(pk)
            return "none" if fn is None else CONN.get(self.node.friend_connection_status(fn), "none")
        return self._call(go)

    def send(self, pk, text, exact=False):
        """exact: send the parts untrimmed, for a peer Toxline that rejoins them byte for byte.
        Chat apps show each part as its own bubble, so for people the edges are trimmed."""
        def go():
            fn = self._fn(pk)
            if fn is None:
                raise RuntimeError("not a Tox friend yet")
            parts = toxcore.split_message(text)
            if not exact:
                parts = [p.strip("\n") for p in parts]
            return [self.node.send_message_raw(fn, p) for p in parts if p.strip() or (exact and p)]
        return self._call(go)

    def set_typing(self, pk, on):
        def go():
            fn = self._fn(pk)
            if fn is not None:
                self.node.set_typing(fn, bool(on))
        try:
            self._call(go)
        except Exception:
            pass

    def set_name(self, name, status_message=None):
        self.name = name
        if status_message is not None:
            self.status_message = status_message

        def go():
            self.node.set_name(name)
            if status_message is not None:
                self.node.set_status_message(status_message)
            self.node.save()
        return self._call(go)
