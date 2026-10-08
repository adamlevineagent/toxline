"""Minimal ctypes binding for c-toxcore (libtoxcore 0.2.x) plus a ToxNode wrapper.

Loads bin/toxcore.dll (and its dependencies libsodium.dll / pthreadVC3.dll) from
the `bin` directory next to this file, or from TOXCORE_DLL if set.

Only the text-messaging subset is bound: identity, savedata, bootstrap, friends,
messages, read receipts, typing, names/status messages.

A Tox instance is NOT thread-safe: call every ToxNode method from the thread that
runs iterate()/run() (or hold your own lock around both).
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import time
from ctypes import (CFUNCTYPE, POINTER, c_bool, c_char_p, c_int, c_size_t,
                    c_uint8, c_uint16, c_uint32, c_void_p)
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger("toxcore")

HERE = Path(__file__).resolve().parent
BIN_DIR = HERE / "bin"
BOOTSTRAP_FILE = HERE / "bootstrap_nodes.json"

# ---------------------------------------------------------------- constants
TOX_PUBLIC_KEY_SIZE = 32
TOX_ADDRESS_SIZE = 38
TOX_MAX_NAME_LENGTH = 128
TOX_MAX_STATUS_MESSAGE_LENGTH = 1007
TOX_MAX_FRIEND_REQUEST_LENGTH = 921
TOX_MAX_MESSAGE_LENGTH = 1372

TOX_CONNECTION_NONE, TOX_CONNECTION_TCP, TOX_CONNECTION_UDP = 0, 1, 2
CONNECTION_NAMES = {0: "NONE", 1: "TCP", 2: "UDP"}
TOX_MESSAGE_TYPE_NORMAL, TOX_MESSAGE_TYPE_ACTION = 0, 1
TOX_SAVEDATA_TYPE_NONE, TOX_SAVEDATA_TYPE_TOX_SAVE, TOX_SAVEDATA_TYPE_SECRET_KEY = 0, 1, 2
TOX_USER_STATUS_NONE, TOX_USER_STATUS_AWAY, TOX_USER_STATUS_BUSY = 0, 1, 2
TOX_LOG_LEVELS = {0: "TRACE", 1: "DEBUG", 2: "INFO", 3: "WARNING", 4: "ERROR"}
UINT32_MAX = 0xFFFFFFFF

TOX_ERR_NEW = ["OK", "NULL", "MALLOC", "PORT_ALLOC", "PROXY_BAD_TYPE", "PROXY_BAD_HOST",
               "PROXY_BAD_PORT", "PROXY_NOT_FOUND", "LOAD_ENCRYPTED", "LOAD_BAD_FORMAT"]
TOX_ERR_FRIEND_ADD = ["OK", "NULL", "TOO_LONG", "NO_MESSAGE", "OWN_KEY", "ALREADY_SENT",
                      "BAD_CHECKSUM", "SET_NEW_NOSPAM", "MALLOC"]
TOX_ERR_SEND = ["OK", "NULL", "FRIEND_NOT_FOUND", "FRIEND_NOT_CONNECTED", "SENDQ", "TOO_LONG", "EMPTY"]
TOX_ERR_BOOTSTRAP = ["OK", "NULL", "BAD_HOST", "BAD_PORT"]


class ToxError(RuntimeError):
    pass


def _errname(table, code):
    return table[code] if 0 <= code < len(table) else str(code)


# ---------------------------------------------------------------- library load
def load_library(path: Optional[str] = None) -> ctypes.CDLL:
    path = path or os.environ.get("TOXCORE_DLL")
    if not path:
        if sys.platform == "win32":
            path = str(BIN_DIR / "toxcore.dll")
        else:   # Linux/macOS: the distro's libtoxcore (e.g. `pacman -S toxcore`, `apt install libtoxcore2`)
            from ctypes import util as ctypes_util
            path = ctypes_util.find_library("toxcore") or "libtoxcore.so"
    d = os.path.dirname(os.path.abspath(path))
    if sys.platform == "win32":
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    return ctypes.CDLL(path)


Tox_p = c_void_p
u8p = POINTER(c_uint8)

# callback prototypes (all end with void *user_data)
LOG_CB = CFUNCTYPE(None, c_void_p, c_int, c_char_p, c_uint32, c_char_p, c_char_p, c_void_p)
SELF_CONN_CB = CFUNCTYPE(None, c_void_p, c_int, c_void_p)
FRIEND_REQUEST_CB = CFUNCTYPE(None, c_void_p, u8p, u8p, c_size_t, c_void_p)
FRIEND_MESSAGE_CB = CFUNCTYPE(None, c_void_p, c_uint32, c_int, u8p, c_size_t, c_void_p)
FRIEND_CONN_CB = CFUNCTYPE(None, c_void_p, c_uint32, c_int, c_void_p)
FRIEND_RECEIPT_CB = CFUNCTYPE(None, c_void_p, c_uint32, c_uint32, c_void_p)
FRIEND_BYTES_CB = CFUNCTYPE(None, c_void_p, c_uint32, u8p, c_size_t, c_void_p)  # name / status msg
FRIEND_TYPING_CB = CFUNCTYPE(None, c_void_p, c_uint32, c_bool, c_void_p)

_lib: Optional[ctypes.CDLL] = None


def lib() -> ctypes.CDLL:
    global _lib
    if _lib is not None:
        return _lib
    L = load_library()
    E = POINTER(c_int)  # every Tox_Err_* out-param is an int-sized enum

    def sig(name, res, *args):
        f = getattr(L, name)
        f.restype = res
        f.argtypes = list(args)

    sig("tox_version_major", c_uint32)
    sig("tox_version_minor", c_uint32)
    sig("tox_version_patch", c_uint32)
    sig("tox_options_new", c_void_p, E)
    sig("tox_options_free", None, c_void_p)
    sig("tox_options_default", None, c_void_p)
    sig("tox_options_set_ipv6_enabled", None, c_void_p, c_bool)
    sig("tox_options_set_udp_enabled", None, c_void_p, c_bool)
    sig("tox_options_set_local_discovery_enabled", None, c_void_p, c_bool)
    sig("tox_options_set_hole_punching_enabled", None, c_void_p, c_bool)
    sig("tox_options_set_start_port", None, c_void_p, c_uint16)
    sig("tox_options_set_end_port", None, c_void_p, c_uint16)
    sig("tox_options_set_tcp_port", None, c_void_p, c_uint16)
    sig("tox_options_set_savedata_type", None, c_void_p, c_int)
    sig("tox_options_set_savedata_data", c_bool, c_void_p, u8p, c_size_t)
    sig("tox_options_set_log_callback", None, c_void_p, LOG_CB)
    sig("tox_new", Tox_p, c_void_p, E)
    sig("tox_kill", None, Tox_p)
    sig("tox_get_savedata_size", c_size_t, Tox_p)
    sig("tox_get_savedata", None, Tox_p, u8p)
    sig("tox_bootstrap", c_bool, Tox_p, c_char_p, c_uint16, u8p, E)
    sig("tox_add_tcp_relay", c_bool, Tox_p, c_char_p, c_uint16, u8p, E)
    sig("tox_self_get_connection_status", c_int, Tox_p)
    sig("tox_iteration_interval", c_uint32, Tox_p)
    sig("tox_iterate", None, Tox_p, c_void_p)
    sig("tox_self_get_address", None, Tox_p, u8p)
    sig("tox_self_get_public_key", None, Tox_p, u8p)
    sig("tox_self_get_nospam", c_uint32, Tox_p)
    sig("tox_self_set_name", c_bool, Tox_p, u8p, c_size_t, E)
    sig("tox_self_get_name_size", c_size_t, Tox_p)
    sig("tox_self_get_name", None, Tox_p, u8p)
    sig("tox_self_set_status_message", c_bool, Tox_p, u8p, c_size_t, E)
    sig("tox_self_set_status", None, Tox_p, c_int)
    sig("tox_self_get_udp_port", c_uint16, Tox_p, E)
    sig("tox_friend_add", c_uint32, Tox_p, u8p, u8p, c_size_t, E)
    sig("tox_friend_add_norequest", c_uint32, Tox_p, u8p, E)
    sig("tox_friend_delete", c_bool, Tox_p, c_uint32, E)
    sig("tox_friend_by_public_key", c_uint32, Tox_p, u8p, E)
    sig("tox_friend_exists", c_bool, Tox_p, c_uint32)
    sig("tox_self_get_friend_list_size", c_size_t, Tox_p)
    sig("tox_self_get_friend_list", None, Tox_p, POINTER(c_uint32))
    sig("tox_friend_get_public_key", c_bool, Tox_p, c_uint32, u8p, E)
    sig("tox_friend_get_name_size", c_size_t, Tox_p, c_uint32, E)
    sig("tox_friend_get_name", c_bool, Tox_p, c_uint32, u8p, E)
    sig("tox_friend_get_status_message_size", c_size_t, Tox_p, c_uint32, E)
    sig("tox_friend_get_status_message", c_bool, Tox_p, c_uint32, u8p, E)
    sig("tox_friend_get_connection_status", c_int, Tox_p, c_uint32, E)
    sig("tox_friend_send_message", c_uint32, Tox_p, c_uint32, c_int, u8p, c_size_t, E)
    sig("tox_self_set_typing", c_bool, Tox_p, c_uint32, c_bool, E)
    sig("tox_callback_self_connection_status", None, Tox_p, SELF_CONN_CB)
    sig("tox_callback_friend_request", None, Tox_p, FRIEND_REQUEST_CB)
    sig("tox_callback_friend_message", None, Tox_p, FRIEND_MESSAGE_CB)
    sig("tox_callback_friend_connection_status", None, Tox_p, FRIEND_CONN_CB)
    sig("tox_callback_friend_read_receipt", None, Tox_p, FRIEND_RECEIPT_CB)
    sig("tox_callback_friend_name", None, Tox_p, FRIEND_BYTES_CB)
    sig("tox_callback_friend_status_message", None, Tox_p, FRIEND_BYTES_CB)
    sig("tox_callback_friend_typing", None, Tox_p, FRIEND_TYPING_CB)
    _lib = L
    return L


def version() -> str:
    L = lib()
    return f"{L.tox_version_major()}.{L.tox_version_minor()}.{L.tox_version_patch()}"


# ---------------------------------------------------------------- helpers
def _buf(data: bytes):
    """ctypes uint8 array copy of `data` (kept alive by the caller's reference)."""
    return (c_uint8 * max(len(data), 1)).from_buffer_copy(data or b"\0")


def _bytes(ptr, length: int) -> bytes:
    return ctypes.string_at(ptr, length) if length else b""


def split_message(text: str, limit: int = TOX_MAX_MESSAGE_LENGTH) -> list[str]:
    """Split text into chunks whose UTF-8 encoding is <= limit bytes.

    Never splits inside a code point; prefers to break after the last newline,
    then the last whitespace, in the second half of the window. Separators stay
    attached to the end of the preceding chunk, so ''.join(chunks) == text.
    """
    if not text:
        return []
    out: list[str] = []
    rest = text
    while rest:
        if len(rest.encode("utf-8")) <= limit:
            out.append(rest)
            break
        # largest prefix (in code points) that fits in `limit` bytes
        lo, hi = 1, len(rest)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if len(rest[:mid].encode("utf-8")) <= limit:
                lo = mid
            else:
                hi = mid - 1
        cut = lo
        window = rest[:cut]
        floor = cut // 2
        brk = window.rfind("\n")
        if brk < floor:
            brk = max((i for i, ch in enumerate(window) if ch.isspace()), default=-1)
        if brk >= floor:
            cut = brk + 1
        out.append(rest[:cut])
        rest = rest[cut:]
    return out


def load_bootstrap_nodes(path: Path = BOOTSTRAP_FILE) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)["nodes"]


# ---------------------------------------------------------------- ToxNode
class ToxNode:
    """One Tox identity backed by a savedata file.

    Hooks (assign callables; all optional):
      on_self_connection(status:int)
      on_friend_request(public_key_hex:str, message:str) -> bool|None  (True = accept)
      on_friend_message(friend_number:int, text:str, msg_type:int)
      on_friend_connection(friend_number:int, status:int)
      on_read_receipt(friend_number:int, message_id:int)
      on_friend_name(friend_number:int, name:str)
      on_friend_status_message(friend_number:int, text:str)
      on_friend_typing(friend_number:int, is_typing:bool)
    """

    def __init__(self, savedata_path: str | os.PathLike, name: Optional[str] = None, *,
                 status_message: Optional[str] = None, udp: bool = True, ipv6: bool = True,
                 local_discovery: bool = True, hole_punching: bool = True,
                 start_port: int = 0, end_port: int = 0, tcp_server_port: int = 0,
                 auto_accept: bool = False, tox_log_level: Optional[int] = None):
        self.L = lib()
        self.savedata_path = Path(savedata_path)
        self.auto_accept = auto_accept
        self.on_self_connection: Optional[Callable] = None
        self.on_friend_request: Optional[Callable] = None
        self.on_friend_message: Optional[Callable] = None
        self.on_friend_connection: Optional[Callable] = None
        self.on_read_receipt: Optional[Callable] = None
        self.on_friend_name: Optional[Callable] = None
        self.on_friend_status_message: Optional[Callable] = None
        self.on_friend_typing: Optional[Callable] = None
        self.connection_status = TOX_CONNECTION_NONE
        self._dirty = False
        self._running = False
        self._cbs: list = []  # keep CFUNCTYPE objects alive for the lifetime of the Tox

        err = c_int(0)
        opts = self.L.tox_options_new(ctypes.byref(err))
        if not opts:
            raise ToxError(f"tox_options_new failed: {err.value}")
        try:
            self.L.tox_options_default(opts)
            self.L.tox_options_set_ipv6_enabled(opts, ipv6)
            self.L.tox_options_set_udp_enabled(opts, udp)
            self.L.tox_options_set_local_discovery_enabled(opts, local_discovery)
            self.L.tox_options_set_hole_punching_enabled(opts, hole_punching)
            if start_port:
                self.L.tox_options_set_start_port(opts, start_port)
            if end_port:
                self.L.tox_options_set_end_port(opts, end_port)
            if tcp_server_port:
                self.L.tox_options_set_tcp_port(opts, tcp_server_port)
            if tox_log_level is not None:
                def _log(_t, level, file, line, func, msg, _ud):
                    if level >= tox_log_level:
                        log.log(10 + 10 * max(0, level - 1),
                                "[tox %s] %s:%d %s: %s", TOX_LOG_LEVELS.get(level, level),
                                (file or b"").decode(errors="replace"), line,
                                (func or b"").decode(errors="replace"),
                                (msg or b"").decode(errors="replace"))
                cb = LOG_CB(_log)
                self._cbs.append(cb)
                self.L.tox_options_set_log_callback(opts, cb)
            saved = None
            if self.savedata_path.exists() and self.savedata_path.stat().st_size > 0:
                saved = _buf(self.savedata_path.read_bytes())
                self.L.tox_options_set_savedata_type(opts, TOX_SAVEDATA_TYPE_TOX_SAVE)
                self.L.tox_options_set_savedata_data(opts, saved, len(saved))
            self.tox = self.L.tox_new(opts, ctypes.byref(err))
            del saved
        finally:
            self.L.tox_options_free(opts)
        if not self.tox:
            raise ToxError(f"tox_new failed: {_errname(TOX_ERR_NEW, err.value)}")

        self._install_callbacks()
        changed = False
        if name is not None and name != self.name:
            self.set_name(name)
            changed = True
        if status_message is not None:
            self.set_status_message(status_message)
            changed = True
        if changed or not self.savedata_path.exists():
            self.save()

    # ------------------------------------------------------------ lifecycle
    def kill(self):
        if getattr(self, "tox", None):
            self.save()
            self.L.tox_kill(self.tox)
            self.tox = None

    close = kill

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.kill()

    def __del__(self):
        try:
            self.kill()
        except Exception:
            pass

    def savedata(self) -> bytes:
        n = self.L.tox_get_savedata_size(self.tox)
        b = (c_uint8 * n)()
        self.L.tox_get_savedata(self.tox, b)
        return bytes(b)

    def save(self):
        data = self.savedata()
        self.savedata_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.savedata_path.with_suffix(self.savedata_path.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.savedata_path)
        self._dirty = False

    def _mark_dirty(self):
        self._dirty = True

    # ------------------------------------------------------------ identity
    @property
    def address(self) -> str:
        """76-hex-char Tox ID (public key + nospam + checksum) to share with friends."""
        b = (c_uint8 * TOX_ADDRESS_SIZE)()
        self.L.tox_self_get_address(self.tox, b)
        return bytes(b).hex().upper()

    @property
    def public_key(self) -> str:
        b = (c_uint8 * TOX_PUBLIC_KEY_SIZE)()
        self.L.tox_self_get_public_key(self.tox, b)
        return bytes(b).hex().upper()

    @property
    def name(self) -> str:
        n = self.L.tox_self_get_name_size(self.tox)
        b = (c_uint8 * max(n, 1))()
        self.L.tox_self_get_name(self.tox, b)
        return bytes(b)[:n].decode("utf-8", "replace")

    def set_name(self, name: str):
        data = name.encode("utf-8")[:TOX_MAX_NAME_LENGTH]
        err = c_int(0)
        if not self.L.tox_self_set_name(self.tox, _buf(data), len(data), ctypes.byref(err)):
            raise ToxError(f"tox_self_set_name failed: {err.value}")
        self._mark_dirty()

    def set_status_message(self, text: str):
        data = text.encode("utf-8")[:TOX_MAX_STATUS_MESSAGE_LENGTH]
        err = c_int(0)
        if not self.L.tox_self_set_status_message(self.tox, _buf(data), len(data), ctypes.byref(err)):
            raise ToxError(f"tox_self_set_status_message failed: {err.value}")
        self._mark_dirty()

    def set_status(self, status: int):
        self.L.tox_self_set_status(self.tox, status)

    @property
    def udp_port(self) -> int:
        err = c_int(0)
        return self.L.tox_self_get_udp_port(self.tox, ctypes.byref(err))

    def get_connection_status(self) -> int:
        return self.L.tox_self_get_connection_status(self.tox)

    # ------------------------------------------------------------ network
    def bootstrap(self, host: str, port: int, public_key_hex: str, tcp_ports: Iterable[int] = ()) -> bool:
        pk = _buf(bytes.fromhex(public_key_hex))
        err = c_int(0)
        ok = bool(self.L.tox_bootstrap(self.tox, host.encode(), port, pk, ctypes.byref(err)))
        if not ok:
            log.debug("bootstrap %s:%d failed: %s", host, port, _errname(TOX_ERR_BOOTSTRAP, err.value))
        for tp in tcp_ports:
            if self.L.tox_add_tcp_relay(self.tox, host.encode(), tp, pk, ctypes.byref(err)):
                ok = True
            else:
                log.debug("tcp relay %s:%d failed: %s", host, tp, _errname(TOX_ERR_BOOTSTRAP, err.value))
        return ok

    def bootstrap_public(self, nodes: Optional[list[dict]] = None, tcp: bool = True) -> int:
        """Bootstrap against the built-in public node list; returns #nodes accepted."""
        ok = 0
        for n in nodes or load_bootstrap_nodes():
            hosts = [n["ipv4"]] + ([n["ipv6"]] if n.get("ipv6") not in (None, "", "-") and n["ipv6"] != n["ipv4"] else [])
            for h in hosts:
                if h in ("", "-"):
                    continue
                if self.bootstrap(h, n["port"], n["public_key"], n.get("tcp_ports", []) if tcp else ()):
                    ok += 1
                    break
        return ok

    def iteration_interval(self) -> int:
        return self.L.tox_iteration_interval(self.tox)

    def iterate(self):
        self.L.tox_iterate(self.tox, None)
        if self._dirty:
            self.save()

    def run(self, until: Optional[Callable[[], bool]] = None, timeout: Optional[float] = None):
        """Iterate until `until()` is true, `timeout` seconds pass, or stop() is called."""
        self._running = True
        deadline = time.monotonic() + timeout if timeout else None
        while self._running:
            self.iterate()
            if until and until():
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            time.sleep(self.iteration_interval() / 1000.0)
        return False

    def stop(self):
        self._running = False

    # ------------------------------------------------------------ friends
    def friend_add(self, address_hex: str, message: str = "Hi! Please add me.") -> int:
        addr = _buf(bytes.fromhex(address_hex))
        msg = message.encode("utf-8")[:TOX_MAX_FRIEND_REQUEST_LENGTH] or b" "
        err = c_int(0)
        fn = self.L.tox_friend_add(self.tox, addr, _buf(msg), len(msg), ctypes.byref(err))
        if fn == UINT32_MAX:
            raise ToxError(f"tox_friend_add failed: {_errname(TOX_ERR_FRIEND_ADD, err.value)}")
        self.save()
        return fn

    def friend_add_norequest(self, public_key_hex: str) -> int:
        pk = _buf(bytes.fromhex(public_key_hex[:2 * TOX_PUBLIC_KEY_SIZE]))
        err = c_int(0)
        fn = self.L.tox_friend_add_norequest(self.tox, pk, ctypes.byref(err))
        if fn == UINT32_MAX:
            raise ToxError(f"tox_friend_add_norequest failed: {_errname(TOX_ERR_FRIEND_ADD, err.value)}")
        self.save()
        return fn

    accept_friend_request = friend_add_norequest

    def friend_delete(self, friend_number: int) -> bool:
        err = c_int(0)
        ok = bool(self.L.tox_friend_delete(self.tox, friend_number, ctypes.byref(err)))
        if ok:
            self.save()
        return ok

    def friend_by_public_key(self, public_key_hex: str) -> Optional[int]:
        pk = _buf(bytes.fromhex(public_key_hex[:2 * TOX_PUBLIC_KEY_SIZE]))
        err = c_int(0)
        fn = self.L.tox_friend_by_public_key(self.tox, pk, ctypes.byref(err))
        return None if fn == UINT32_MAX else fn

    def friend_public_key(self, friend_number: int) -> Optional[str]:
        b = (c_uint8 * TOX_PUBLIC_KEY_SIZE)()
        err = c_int(0)
        if not self.L.tox_friend_get_public_key(self.tox, friend_number, b, ctypes.byref(err)):
            return None
        return bytes(b).hex().upper()

    def friend_name(self, friend_number: int) -> Optional[str]:
        err = c_int(0)
        n = self.L.tox_friend_get_name_size(self.tox, friend_number, ctypes.byref(err))
        if err.value:
            return None
        b = (c_uint8 * max(n, 1))()
        if not self.L.tox_friend_get_name(self.tox, friend_number, b, ctypes.byref(err)):
            return None
        return bytes(b)[:n].decode("utf-8", "replace")

    def friend_status_message(self, friend_number: int) -> Optional[str]:
        err = c_int(0)
        n = self.L.tox_friend_get_status_message_size(self.tox, friend_number, ctypes.byref(err))
        if err.value:
            return None
        b = (c_uint8 * max(n, 1))()
        if not self.L.tox_friend_get_status_message(self.tox, friend_number, b, ctypes.byref(err)):
            return None
        return bytes(b)[:n].decode("utf-8", "replace")

    def friend_connection_status(self, friend_number: int) -> int:
        err = c_int(0)
        return self.L.tox_friend_get_connection_status(self.tox, friend_number, ctypes.byref(err))

    def friend_list(self) -> list[int]:
        n = self.L.tox_self_get_friend_list_size(self.tox)
        arr = (c_uint32 * max(n, 1))()
        self.L.tox_self_get_friend_list(self.tox, arr)
        return list(arr)[:n]

    # ------------------------------------------------------------ messaging
    def send_message_raw(self, friend_number: int, text: str, action: bool = False) -> int:
        """Send one message (<= TOX_MAX_MESSAGE_LENGTH UTF-8 bytes). Returns message id."""
        data = text.encode("utf-8")
        err = c_int(0)
        mid = self.L.tox_friend_send_message(
            self.tox, friend_number, TOX_MESSAGE_TYPE_ACTION if action else TOX_MESSAGE_TYPE_NORMAL,
            _buf(data), len(data), ctypes.byref(err))
        if err.value:
            raise ToxError(f"tox_friend_send_message failed: {_errname(TOX_ERR_SEND, err.value)}")
        return mid

    def send_message(self, friend_number: int, text: str, action: bool = False) -> list[int]:
        """Send arbitrarily long text, split on safe boundaries. Returns message ids."""
        return [self.send_message_raw(friend_number, chunk, action) for chunk in split_message(text)]

    def set_typing(self, friend_number: int, typing: bool) -> bool:
        err = c_int(0)
        return bool(self.L.tox_self_set_typing(self.tox, friend_number, typing, ctypes.byref(err)))

    # ------------------------------------------------------------ callbacks
    def _hook(self, name, *args):
        fn = getattr(self, name)
        if fn is None:
            return None
        try:
            return fn(*args)
        except Exception:
            log.exception("ToxNode hook %s raised", name)
            return None

    def _install_callbacks(self):
        L, t = self.L, self.tox

        def self_conn(_t, status, _ud):
            self.connection_status = status
            self._hook("on_self_connection", status)

        def friend_request(_t, pk, msg, length, _ud):
            pk_hex = _bytes(pk, TOX_PUBLIC_KEY_SIZE).hex().upper()
            text = _bytes(msg, length).decode("utf-8", "replace")
            accept = self._hook("on_friend_request", pk_hex, text)
            if accept or (accept is None and self.auto_accept):
                try:
                    self.friend_add_norequest(pk_hex)
                except ToxError:
                    log.exception("auto-accept failed")

        def friend_message(_t, fn, mtype, msg, length, _ud):
            self._hook("on_friend_message", fn, _bytes(msg, length).decode("utf-8", "replace"), mtype)

        def friend_conn(_t, fn, status, _ud):
            self._hook("on_friend_connection", fn, status)

        def receipt(_t, fn, mid, _ud):
            self._hook("on_read_receipt", fn, mid)

        def fname(_t, fn, b, length, _ud):
            self._mark_dirty()
            self._hook("on_friend_name", fn, _bytes(b, length).decode("utf-8", "replace"))

        def fstatus(_t, fn, b, length, _ud):
            self._hook("on_friend_status_message", fn, _bytes(b, length).decode("utf-8", "replace"))

        def ftyping(_t, fn, typing, _ud):
            self._hook("on_friend_typing", fn, bool(typing))

        pairs = [
            (L.tox_callback_self_connection_status, SELF_CONN_CB(self_conn)),
            (L.tox_callback_friend_request, FRIEND_REQUEST_CB(friend_request)),
            (L.tox_callback_friend_message, FRIEND_MESSAGE_CB(friend_message)),
            (L.tox_callback_friend_connection_status, FRIEND_CONN_CB(friend_conn)),
            (L.tox_callback_friend_read_receipt, FRIEND_RECEIPT_CB(receipt)),
            (L.tox_callback_friend_name, FRIEND_BYTES_CB(fname)),
            (L.tox_callback_friend_status_message, FRIEND_BYTES_CB(fstatus)),
            (L.tox_callback_friend_typing, FRIEND_TYPING_CB(ftyping)),
        ]
        for register, cb in pairs:
            self._cbs.append(cb)
            register(t, cb)


def iterate_all(nodes: list[ToxNode], until: Callable[[], bool], timeout: float) -> bool:
    """Drive several nodes from one thread until `until()` is true or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for n in nodes:
            n.iterate()
        if until():
            return True
        time.sleep(min(n.iteration_interval() for n in nodes) / 1000.0)
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("libtoxcore", version())
