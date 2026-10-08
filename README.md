# Toxline

**Let invited people chat, from their own Tox client, with a Codex agent working in a real
Codex Desktop thread on your machine.** You watch every conversation exactly as they see it,
and you steer the agent privately in its normal Codex chat.

```
 their Tox client ⇄ Tox network ⇄ toxlined (your PC) ──send_message_to_thread──▶ Codex Desktop thread
                                      ▲                                               │
                                      └────────────────── tox-send ◀──────────────────┘
```

Toxline was built to give a small, invited audience (5–20 people) an agent they can question
in depth about a project: it reads your docs and code, answers in a chat app they already use,
and you stay in the loop. Nothing about it is specific to that use; it's a general bridge
between Tox and Codex threads.

- **Real threads, not a chatbot shell.** Each guest is bound to an ordinary Codex Desktop thread
  that you set up (instructions, files, tools). You open it, read it, and talk to the agent
  there like any other thread.
- **Delivered the moment it arrives.** A guest's message goes into the thread through Codex
  Desktop's own `send_message_to_thread`. An idle agent starts a turn; a busy one gets the
  message steered into its current turn, so a correction interrupts work already in progress.
  Nothing is queued or batched, and it works whether or not the thread is open on screen.
- **The agent decides what to say.** Its private work stays private. Only text it sends with
  `tox-send` reaches the guest, and you can hold every outgoing message for review.
- **The guest's view.** A local web viewer shows each chat exactly as the guest sees it, live
  and in full history, with owner-only details (delivery ticks, whether each message reached
  the agent, held replies). Setup for new guests happens there too.
- **Real Tox.** The agent has its own Tox identity (toxcore via ctypes): friend requests, read
  receipts, typing indicator while the agent works, offline queueing, long-message splitting.

## Requirements

- Windows 10/11 with **Codex Desktop** installed and running (toxline drives its threads)
- Python 3.11+ on PATH (standard library only; no pip installs)
- A build of **c-toxcore** (`toxcore.dll`). `tox/build.bat` and [`tox/README.md`](tox/README.md)
  build it from source with MSVC + vcpkg in a few minutes.

## Quick start

1. **Build toxcore** once: follow [`tox/README.md`](tox/README.md). You end up with
   `tox\bin\toxcore.dll`, `libsodium.dll` and `pthreadVC3.dll`. Check it with
   `python -X utf8 tox\selftest.py` (two local nodes befriend each other and exchange messages).
2. **Start toxline:** double-click `Start-Toxline.cmd`. It starts the service and opens the viewer
   at http://127.0.0.1:8765/. The agent's Tox ID is at the top-left; click it to copy.
3. **Make it yours:** ⚙ Settings: your name (how agents refer to you), the agent's Tox name and
   status line, an optional topic and an optional *reference map* (a file agents should start
   research from), and the friend-request greeting.
4. **Invite someone.** In Codex Desktop, create the thread that should answer them and set it up
   the way you like. Then either:
   - give them the agent's Tox ID; their friend request appears in the viewer's sidebar, and
     **Set up guest** binds them to a thread, or
   - click **+ Guest**, paste *their* Tox ID (from their client's profile), and pick the thread
     (or paste its ID / `codex://threads/…` link). The agent sends them a friend request.

   Toxline posts a short note into the thread telling the agent who it's talking to and how to
   reply. From then on, their messages arrive as `[Tox message from <name>]` blocks.

Optional: `Install-Autostart.cmd` starts toxline when you sign in (logs go to
`state\toxline.log`); `Remove-Autostart.cmd` undoes it.

## The viewer

- **Sidebar:** every guest with online status, unread count and last message; pending friend
  requests (including archived guests coming back, with one-click restore).
- **Chat:** the guest's messages on the right, the agent's on the left, as in their client.
  *Details* toggles owner-only information.
- **Hold outgoing:** the agent's replies wait for you: Send now, Edit & send, or Discard.
- **⋯:** notes about the guest, rebind to another thread, pause (their messages are kept but not
  delivered; replies are held), archive (ends the Tox friendship, keeps history), delete.
- **Open agent thread ↗** jumps to the thread in Codex Desktop.
- **Test guests:** a simulated person you type as yourself, for trying a thread out.

## For the agent: `tox-send`

From the agent's PowerShell (Codex's shell on Windows):

```powershell
& "<toxline>\bin\tox-send.ps1" "message"           # send to this thread's guest
& "<toxline>\bin\tox-send.ps1" --file reply.md     # long, multi-line or quote-heavy text
& "<toxline>\bin\tox-send.ps1" --who               # who this thread talks to + recent chat
& "<toxline>\bin\tox-send.ps1" --to Sam "message"  # threads shared by several guests (or --to all)
"text" | & "<toxline>\bin\tox-send.ps1"            # pipeline input
```

The guest is found from the thread the agent runs in (`CODEX_THREAD_ID`), so an agent can't
message the wrong person. The result reads DELIVERED (their client confirmed), SENT, QUEUED
(they're offline; it goes out when they connect) or HELD (waiting for your review).
`tox-send` is plain PowerShell, so it runs inside Codex's sandbox. It talks to toxline on
localhost and falls back to an outbox folder if the sandbox blocks network access.
`bin\tox-send.cmd` exists for other shells, but cmd mangles quotes and `%VARS%` in arguments,
so use `--file` there.

## Shared threads

Several guests can share one thread: pick a thread that's already bound when adding someone.
The agent sees everyone's messages (each labelled with the sender) and chooses who each reply
goes to with `--to`. Each guest only sees what's sent to them.

## How delivery works, and its limits

Codex Desktop serves its built-in thread tools (`send_message_to_thread`, `read_thread`,
`wait_threads`…) to its own agents over a local named pipe. Toxline finds that pipe (its name
changes every time Desktop starts) and calls `send_message_to_thread` the same way an agent
would. Desktop then starts or steers the turn itself, so the thread updates live in the UI.
Toxline keeps one small **Toxline service** thread in Codex, because `wait_threads` (used for the
typing indicator) needs a calling thread other than the one it watches.

This relies on **undocumented Codex Desktop internals**. They worked with Codex Desktop
26.1002 (codex 0.162) and may change in any update. If Desktop isn't running, toxline falls back
to its own `codex app-server`, which can only deliver to threads that aren't open in Desktop.

## Security notes

- **Who can reach an agent:** only Tox keys you've added as guests. Strangers' friend requests
  just appear in the sidebar for you to decide.
- **What guests can make the agent do:** the default brief says guests can ask anything but
  only you can direct the agent's actions. What actually bounds the agent is the thread's own
  Codex permissions, which you set. Give guest threads the least access they need.
- **Codex Desktop's tool pipe** accepts any local process on Windows, so anything running as
  your user could do what toxline does. Toxline doesn't change that, but be aware of it.
- **Secrets:** the agent's Tox secret key is in `state\tox\agent.tox`. The viewer and API
  listen on 127.0.0.1 only and have no authentication; don't expose the port.

## Testing without a model or a second person

- `python toxlined.py --no-tox --ingress fake --port 8799` with `TOXLINE_HOME` set to a scratch
  folder runs a stand-in agent that replies through the real `tox-send` path. Use test guests in
  the viewer.
- `python tools\tox_peer.py --profile alice --add <AGENT_TOX_ID>` and
  `--say "hello" --wait 120` play a guest over the real Tox network and print JSON events.
- `tools\find_codex_pipe.py` and `tools\read_thread.py` help debug the Codex side.

## Layout

| Path | What |
| --- | --- |
| `toxline/daemon.py` | the service: Tox events, delivery, sending, holds, the HTTP API |
| `toxline/db.py` | the journal (`state/toxline.sqlite3`), the single source of truth |
| `toxline/pipe_ingress.py` | delivery via Codex Desktop `send_message_to_thread`, thread watching |
| `toxline/codex_ingress.py` | fallback delivery via toxline's own `codex app-server` |
| `toxline/tox_transport.py` | the agent's Tox identity |
| `toxline/config.py` | your settings (`state/config.json`) |
| `toxline/persona_default.md` | brief for threads toxline creates itself |
| `bin/tox-send.ps1` | the agent's send command |
| `viewer/` | the viewer (vanilla JS, served by the service) |
| `tox/` | toxcore build script, Python binding (`toxcore.py`) and self-test |
| `tools/` | test peer and debugging helpers |

All state lives in `state/` (or `TOXLINE_HOME`) and is never committed.

## License

MIT, see [LICENSE](LICENSE). Toxline loads c-toxcore at runtime; c-toxcore itself is GPLv3
and is not included here. You build it yourself with `tox/build.bat`.
