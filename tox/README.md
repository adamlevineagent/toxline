# toxline/tox — real Tox transport for Python on Windows

A native c-toxcore **v0.2.23** build (x64, MSVC) plus a ctypes binding (`toxcore.py`) that
Python 3.13 uses to speak the real Tox protocol. It talks to qTox, uTox, aTox, TRIfA and other clients.

## Files

| Path | What |
|---|---|
| `bin/toxcore.dll` | libtoxcore 0.2.23 (text-only: no toxav), built here from source |
| `bin/libsodium.dll` | libsodium 1.0.22 (vcpkg `libsodium:x64-windows@1.0.22#1`) |
| `bin/pthreadVC3.dll` | PThreads4W 3.0.0 (vcpkg `pthreads:x64-windows@3.0.0#14`) |
| `toxcore.py` | ctypes binding + `ToxNode` class + `split_message` helper |
| `bootstrap_nodes.json` | 8 public bootstrap nodes taken from https://nodes.tox.chat/json (2026-10-07), all UDP+TCP up |
| `selftest.py` | end-to-end test with two real nodes |
| `build.bat` | reproducible build script (configure + build + copy DLLs to `bin/`) |
| `vcpkg/`, `c-toxcore/`, `build/` | build inputs and outputs (git-ignored; delete them freely, `bin/` is self-contained) |

SHA-256 of the built artifacts:
```
bd53dc1b01d2c87a2c58395acea8deca3d50f93d8ea2de2639aa37c71a02f872  toxcore.dll
740eb7f05048ce346857c39d7c01b6abd574b44f32191cb44fe293f453aa3d61  libsodium.dll
928bc67c95aaffca530070580fd8f3433fa7894b87d7f0872efdb1ed18d0e7fa  pthreadVC3.dll
```
The DLLs need the VC++ 2015-2022 runtime (`vcruntime140.dll`), which most Windows machines already have.

## How it was built (reproducible)

Toolchain: VS 2022 Build Tools MSVC 14.44.35207 (cl 19.44.35213), Windows SDK 10.0.26100, CMake 4.1.0, Ninja 1.13.1.
vcpkg has no `toxcore` port, so c-toxcore is built with CMake against vcpkg-provided libsodium, pthreads and pkgconf.

```powershell
cd toxline\tox
git clone https://github.com/microsoft/vcpkg.git vcpkg          # used commit 2750401336fb7c95f6619657a46a7e798661341c
.\vcpkg\bootstrap-vcpkg.bat -disableMetrics                        # vcpkg tool 2026-09-26
.\vcpkg\vcpkg.exe install libsodium pthreads pkgconf --triplet x64-windows
git clone https://github.com/TokTok/c-toxcore.git c-toxcore
git -C c-toxcore checkout v0.2.23                                  # d9ca3c577e5abd4303d180eb5270167b4133ea4c
git -C c-toxcore submodule update --init                           # third_party/cmp @ 52bfcfa17d2e
.\build.bat
```

`build.bat` loads vcvars64 (found via vswhere) and runs:
```
cmake -S c-toxcore -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_TOOLCHAIN_FILE=vcpkg\scripts\buildsystems\vcpkg.cmake
  -DVCPKG_TARGET_TRIPLET=x64-windows -DVCPKG_MANIFEST_MODE=OFF
  -DPKG_CONFIG_EXECUTABLE=vcpkg\installed\x64-windows\tools\pkgconf\pkgconf.exe
  -DENABLE_SHARED=ON -DENABLE_STATIC=OFF -DCMAKE_WINDOWS_EXPORT_ALL_SYMBOLS=ON
  -DBUILD_TOXAV=OFF -DDHT_BOOTSTRAP=OFF -DBOOTSTRAP_DAEMON=OFF
  -DUNITTEST=OFF -DAUTOTEST=OFF -DBUILD_FUN_UTILS=OFF -DBUILD_MISC_TESTS=OFF
cmake --build build --target toxcore_shared
```
then copies `toxcore.dll`, `libsodium.dll`, `pthreadVC3.dll` into `bin/`.

Notes: `VCPKG_MANIFEST_MODE=OFF` matters, because c-toxcore ships a `vcpkg.json` that would otherwise
pull opus/libvpx (libvpx fails to build here, and we do not need A/V). `CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS`
is needed because toxcore has no `__declspec(dllexport)` annotations.

## API summary (`toxcore.py`)

```python
from toxcore import ToxNode, split_message, CONNECTION_NAMES

node = ToxNode("agent.tox", "Agent", status_message="AI agent", auto_accept=False)
print(node.address)          # 76-hex Tox ID to give to people
node.bootstrap_public()      # UDP bootstrap + TCP relays from bootstrap_nodes.json

node.on_self_connection   = lambda status: ...           # 0 NONE / 1 TCP / 2 UDP
node.on_friend_request    = lambda pk_hex, msg: True     # return True to accept
node.on_friend_message    = lambda fn, text, mtype: node.send_message(fn, "echo: " + text)
node.on_friend_connection = lambda fn, status: ...
node.on_read_receipt      = lambda fn, msg_id: ...
node.on_friend_name / on_friend_status_message / on_friend_typing

node.run()                   # loop: tox_iterate + sleep(tox_iteration_interval); node.stop() to exit
```

* `ToxNode(savedata_path, name=None, *, status_message, udp=True, ipv6=True, local_discovery=True,
  hole_punching=True, start_port, end_port, tcp_server_port, auto_accept=False, tox_log_level=None)`
  loads the savedata file if present, otherwise creates a new identity and writes it.
* Identity: `address`, `public_key`, `name`, `set_name()`, `set_status_message()`, `set_status()`,
  `udp_port`, `get_connection_status()`, `savedata()`, `save()`.
* Network: `bootstrap(host, port, pk_hex, tcp_ports=())` (tox_bootstrap + tox_add_tcp_relay),
  `bootstrap_public()`, `iterate()`, `iteration_interval()`, `run(until=None, timeout=None)`, `stop()`,
  module-level `iterate_all(nodes, until, timeout)` to drive several nodes in one thread.
* Friends: `friend_add(address_hex, msg)`, `friend_add_norequest(pk_hex)` (alias `accept_friend_request`),
  `friend_delete(fn)`, `friend_by_public_key(pk_hex)`, `friend_public_key(fn)`, `friend_name(fn)`,
  `friend_status_message(fn)`, `friend_connection_status(fn)`, `friend_list()`.
* Messages: `send_message(fn, text)` returns a list of message ids and splits text over
  TOX_MAX_MESSAGE_LENGTH (1372 bytes) via `split_message()`. Splits never break a UTF-8 code point and
  prefer newline, then whitespace, boundaries; `''.join(chunks) == text`. `send_message_raw()` sends one
  chunk. `set_typing(fn, bool)`.
* Savedata is written atomically (tmp + `os.replace`) after friend add/accept/delete, name or status
  changes, friend renames (on the next `iterate()`), and in `kill()`. **The savedata holds the secret
  key unencrypted. Protect the file.**
* All ctypes callbacks are held in `self._cbs`, so they are not garbage-collected. Exceptions in hooks
  are logged and swallowed. A Tox instance is not thread-safe: use one thread per node, or lock around it.
* `TOXCORE_DLL` env var overrides the DLL path. Low-level `toxcore.lib()` exposes the raw ctypes functions.

## Test result

`python -X utf8 selftest.py` (2026-10-07). A sends a friend request to B. B accepts.
A sends a 3-line unicode message (emoji, CJK, RTL) and a 5460-byte message, which goes out as 4 chunks.
B receives all of them byte-identical and A gets every read receipt. The test also checks the typing
indicator, friend name and status message, a savedata reload (same Tox ID, friend kept), and that the
public DHT is reachable:

```
libtoxcore 0.2.23  long message = 5460 bytes -> 4 chunks
[  0.02s] bootstrapped A on 8 nodes, B on 8 nodes (+TCP relays)
[  0.02s] A sent friend request (friend #0)
[  9.04s] b self connection -> UDP
[ 11.05s] a self connection -> UDP
[ 12.57s] B got friend request from 4F0D42DED0F2E549... msg='selftest: please accept'
[ 14.25s] a friend 0 connection -> UDP
[ 14.26s] A sent 5 messages, ids=[1, 2, 3, 4, 5]
[ 14.36s] B received all 5 messages intact; A got 5 read receipts (103 ms send->all receipts)
[ 14.36s] typing events seen by B: [False, True, False]; A sees B's name: 'selftest-B'; status msg: 'I am B'
[ 14.37s] savedata reload OK (same Tox ID, friend persisted)
[ 23.41s] public DHT: A(reloaded)=UDP B=UDP (B first DHT connect at 9.04s)
SELFTEST PASS
```
`selftest.py --no-internet` (no public bootstrap, local only) also passes in about 10 s.
Public DHT connect (self status UDP) takes about 9-11 s from a cold start.

## Caveats

* Windows Firewall: python.exe already had inbound Allow rules (Private+Public), so no prompt appeared.
  On a fresh machine, the first run will open a firewall prompt for python.exe (UDP 33445+ and LAN discovery).
  Outbound-only TCP relays work without any inbound rule.
* Each process binds the first free UDP port in 33445-33545. Several nodes on one box are fine.
* `bootstrap_nodes.json` is a snapshot. To refresh it, re-pull https://nodes.tox.chat/json and pick nodes
  with `status_udp` and `status_tcp` both true.
* Plain text and action messages only: no file transfer, A/V, conferences or groups are bound
  (the DLL contains them, and they can be bound later).
