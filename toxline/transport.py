"""Transports move text between toxline and the people on the other end.

ToxTransport speaks real Tox through toxcore. LoopbackTransport is an in-process
stand-in where the "remote person" is driven from the viewer's test box, which
lets the whole pipeline run before (or without) a real Tox client.

Both expose the same small surface to the daemon:
  start(), stop(), address(), add_friend(tox_id_or_key, greeting),
  remove_friend(pk), send(pk, text) -> [msg ids], friend_online(pk)
and call back into handlers set on .on_* attributes.
"""
import itertools
import threading
import time


class Transport:
    name = "base"

    def __init__(self):
        self.on_message = lambda pk, text: None
        self.on_receipt = lambda pk, msg_id: None
        self.on_connection = lambda pk, status: None
        self.on_friend_request = lambda pk, greeting: None
        self.on_friend_name = lambda pk, name: None
        self.on_self_connection = lambda status: None
        # Files: on_file_offer(pk, size, name) -> (path, ref) to accept or None to decline;
        # on_file_done(pk, ref, ok, detail) when a transfer either way finishes or fails.
        self.on_file_offer = lambda pk, size, name: None
        self.on_file_done = lambda pk, ref, ok, detail="": None

    def send_file(self, pk, path, ref, name=None):
        raise RuntimeError("this transport can't send files")

    def friend_online(self, pk):
        return False

    def set_typing(self, pk, on):
        pass

    def accept_request(self, pk):
        pass

    def ensure_friend(self, pk):
        pass


class LoopbackTransport(Transport):
    """Simulated remote side. inject() plays the person typing in their client."""
    name = "loopback"

    def __init__(self):
        super().__init__()
        self._ids = itertools.count(1)
        self.friends = set()
        self.self_status = "none"

    def start(self):
        self.self_status = "udp"
        self.on_self_connection("udp")

    def stop(self):
        pass

    def address(self):
        return "LOOPBACK" + "0" * 68

    def add_friend(self, ident, greeting=""):
        pk = ident.upper()[:64]
        self.friends.add(pk)
        threading.Timer(0.2, lambda: self.on_connection(pk, "udp")).start()
        return pk

    def remove_friend(self, pk):
        self.friends.discard(pk.upper())

    def friend_online(self, pk):
        return pk.upper() in self.friends

    def send(self, pk, text, exact=False):
        ids = [next(self._ids)]
        # Simulated client acknowledges shortly after, like a real read receipt.
        threading.Timer(0.3, lambda: [self.on_receipt(pk, i) for i in ids]).start()
        return ids

    def inject(self, pk, text):
        self.on_message(pk.upper(), text)

    def send_file(self, pk, path, ref, name=None):
        threading.Timer(0.3, lambda: self.on_file_done(pk, ref, True, "")).start()

    def inject_file(self, pk, data, name):
        """Play the remote side sending a file (test contacts)."""
        offer = self.on_file_offer(pk.upper(), len(data), name)
        if offer:
            path, ref = offer
            with open(path, "wb") as f:
                f.write(data)
            self.on_file_done(pk.upper(), ref, True, "")


