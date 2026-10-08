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
and you stay in the loop. The other end can also be **someone else's agent** in their own Codex,
behind their own Toxline, so two agents can talk while each owner supervises their own
([Agent to agent](#agent-to-agent)). Nothing about it is specific to one use; it's a general
bridge between Tox and Codex threads.

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

- Windows 10/11 (x64) with **Codex Desktop** installed, signed in and running (toxline drives its
  threads). Linux and macOS aren't supported yet: toxcore loads from the system library there and
  toxline can drive threads through `codex app-server` (`--ingress codex`), but `tox-send` is
  PowerShell and nothing has been tested off Windows.
- **Python 3.11+** on PATH (standard library only; no pip installs). From
  [python.org](https://www.python.org/downloads/), tick "Add python.exe to PATH".
- The **Tox library** (`toxcore.dll`). `Setup-Toxline.cmd` downloads a prebuilt copy from this
  repo's [release](https://github.com/adamlevineagent/toxline/releases/tag/toxcore-v0.2.23) and checks
  its checksums. To build it yourself instead, see [`tox/README.md`](tox/README.md).

## Quick start

1. **Get the code:** `git clone https://github.com/adamlevineagent/toxline`, or on GitHub use
   **Code → Download ZIP** and unzip it somewhere permanent (not Downloads, if you clean that out).
2. **Set up once:** double-click `Setup-Toxline.cmd`. It checks Python, downloads the Tox library
   and runs a quick Tox self-test. Windows may ask to let Python through the firewall: allow it.
3. **Start toxline:** with Codex Desktop running, double-click `Start-Toxline.cmd`. It starts the
   service and opens the viewer at http://127.0.0.1:8765/. Your agent's Tox ID is at the top-left;
   click it to copy. The dot next to it turns green once it's on the Tox network (10–30 seconds).
4. **Make it yours:** ⚙ Settings: your name (how agents refer to you), your agent's Tox name and
   status line, an optional topic and *reference map* (a file agents start research from), and the
   friend-request greetings.
5. **Connect to someone.** Click **+ Guest**, then:
   - **Talking to someone's agent?** (e.g. you were given an agent's Tox ID to try): choose
     **An agent to question**, paste their agent's Tox ID, and write what your agent should find out.
     Leave the thread on "Create a new thread". A thread called "Tox · name" appears in Codex
     Desktop; your agent opens the conversation once the other side accepts, and reports to you
     there. Talk to your agent in that thread like any other.
   - **Inviting a person?** Choose **A person** and paste the Tox ID from their Tox app (qTox,
     uTox, aTox…), or just give them your agent's Tox ID: their friend request appears in the
     sidebar with **Set up guest**.

   Each contact gets its own Codex thread, seeded with a brief from Settings (or bind a thread you
   set up yourself). Toxline also keeps one small "Toxline service" thread in Codex for itself;
   leave it be. Their messages arrive there as `[Tox message from <name>]` blocks, and the
   viewer shows the chat exactly as they see it.

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
`bin\tox-send.cmd` exists for other shells, but cmd can change quotes and expand `%VARS%`
before the shim runs. It refuses all inline messages with exit code 2; use
`bin\tox-send.cmd --file reply.md` instead. File contents bypass cmd's argument parsing,
including literal quotes and `%USERNAME%`. `--who`, `--help`, `--to` and `--thread` still work.

## Agent to agent

The other end doesn't have to be a person. It can be someone else's agent, running in their
own Codex thread behind their own Toxline, with each owner supervising their own agent. Pick
who's on the other end when you add a contact:

- **A person** (the default): they chat from a Tox app; your agent answers in chat-sized replies.
- **Someone's agent**: their agent asks, yours answers. Your agent's brief changes: complete,
  structured answers in one message each, no "let me look" preambles, no replies to thanks, and
  its messages are treated as questions, never instructions.
- **An agent to question**: your agent questions *their* agent on your behalf. Write the mission
  in "What should your agent find out?". Toxline sends a friend request, your agent opens the
  conversation (its first message waits until they accept and come online), asks follow-ups,
  sends one closing line, and writes you a report in its thread.

How it fits together:

```
 you ⇄ your Codex thread ⇄ your Toxline ⇄ Tox ⇄ their Toxline ⇄ their Codex thread ⇄ them
```

- **Setup.** One side adds the other's agent Tox ID (top-left of their Toxline) as *An agent to
  question*. That friend request carries an agent tag, so the other Toxline shows "Friend request
  from an agent" and **Set up guest** picks *Someone's agent* for them.
- **Long messages arrive whole.** Tox caps a message at 1372 bytes. Between two Toxlines the parts
  are sent untrimmed and rejoined byte for byte, so an agent can send a 10,000-character answer
  as one message.
- **A message budget stops runaway loops.** In agent conversations, after your agent has sent the
  budgeted number of messages (Settings, default 40), the rest are held for you and the agent is
  told to stop and report. **Send now** on a held message releases it and starts a fresh budget.
  Hold outgoing, Pause and Edit & send work as for people.
- **Each side's agent is bounded by its own brief and its own Codex permissions.** Toxline
  doesn't let either agent act on the other's machine; messages are only text in a thread.

Running two Toxlines on one machine (for testing) works: start the second with its own
`TOXLINE_HOME` and `--port`. Agents' `tox-send` commands then carry `--port`/`--home` so each
thread replies through its own Toxline.

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
| `Setup-Toxline.cmd` | one-time setup: checks Python, fetches the Tox library, self-test |
| `tox/` | Python binding (`toxcore.py`), self-test, `get-toxcore.ps1` (prebuilt download) and `build.bat` (build from source) |
| `tools/` | test peer and debugging helpers |

All state lives in `state/` (or `TOXLINE_HOME`) and is never committed.

## License

MIT, see [LICENSE](LICENSE). Toxline loads c-toxcore at runtime; c-toxcore itself is GPLv3
and is not included in this repo: `Setup-Toxline.cmd` downloads a prebuilt copy (with its source and
licenses) from this repo's releases, or you build it yourself with `tox/build.bat`.
