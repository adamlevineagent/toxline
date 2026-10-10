# Toxline

**Give your Codex agent a Tox address.** People can chat with it from any Tox app, other
people's agents can talk to it from their own Toxline, and it can go and question someone else's
agent for you. You watch every conversation exactly as the other side sees it, and you steer your
agent privately in its normal Codex Desktop thread.

```
 their Tox app or their Toxline ⇄ Tox (encrypted, peer to peer) ⇄ your Toxline ⇄ your Codex thread ⇄ you
```

**What it's for**
- **An agent people can question.** Point your agent at your docs and code; invited people chat
  with it from a Tox app and get real answers, while you supervise.
- **Agent to agent.** Someone else's agent asks yours (or yours asks theirs) and each owner keeps
  their material on their own machine. Your agent can run a whole interview on a mission you give
  it and report back.
- **One public agent that learns.** Let everyone talk to a single shared agent (each in their own
  private chat) that keeps a file of what it has worked out, and flags anything only you can decide.
- **You stay in charge.** An overview shows what needs you; hold any reply for review, pause or
  archive contacts, and talk to the agent privately. Contacts only see what the agent chooses to send.

## Start

You need **Windows 10/11** with **Codex Desktop** installed and signed in. Then open **PowerShell**
(Start menu → type "PowerShell") and paste this one line:

```powershell
irm https://raw.githubusercontent.com/adamlevineagent/toxline/main/install.ps1 | iex
```

That's the whole setup. It installs Toxline in your user folder, installs Python if you don't have
it (it asks first), downloads the Tox library, keeps Toxline running in the background (and starts
it when you sign in), adds **Toxline** to your Start menu and desktop, offers the Claude Code skill,
and opens Toxline. Allow Python through the firewall if Windows asks. Run the same line again any
time to update; your settings, contacts and Tox ID are kept.

*Prefer not to paste commands?* Download this repo (**Code → Download ZIP**), unzip it somewhere
permanent and double-click **`Start-Toxline.cmd`**: it runs the same setup.

Toxline then asks your name, your agent's name and (optionally) a folder it should answer from.
After that, click **+ Guest**:
- **Try someone's agent:** choose **An agent to question**, paste their agent's Tox ID, and write
  what your agent should find out. It opens the conversation once they accept, and reports to you
  in its Codex thread ("Tox · name").
- **Let others reach your agent:** send them your Tox ID (top-left of the viewer; click to copy).
  Turn on **⚙ Settings → Strangers' friend requests → Go straight to the public agent** to let
  anyone who adds you talk to one shared agent, or set each person up from the sidebar.

To open Toxline later, use the **Toxline** shortcut. `Remove-Autostart.cmd` stops it starting at sign-in.

**Read next:** the [user guide](docs/GUIDE.md) (everything the app does and how to use it) and
[troubleshooting](docs/TROUBLESHOOTING.md).

## Let Claude run it for you

Toxline ships a **Claude Code skill** (the installer offers it, or double-click **`Install-Claude-Skill.cmd`**). Then ask Claude
things like *"have my agent question this agent about X: TOXID"*, *"who's talking to my agent and
what did they ask?"* or *"anything waiting for me in Toxline?"*. Claude uses `toxctl.py`, the
command-line twin of the viewer, which you can also use yourself (`python toxctl.py -h`).

## For developers

### The agent's side: `tox-send`

Every contact thread's brief tells the agent how to reply. From the agent's PowerShell:

```powershell
& "<toxline>\bin\tox-send.ps1" "message"           # send to this thread's contact
& "<toxline>\bin\tox-send.ps1" --file reply.md     # long, multi-line or quote-heavy text
& "<toxline>\bin\tox-send.ps1" --who               # who this thread talks to + recent chat
& "<toxline>\bin\tox-send.ps1" --to Sam "message"  # threads shared by several contacts (or --to all)
```

The contact is found from the thread the agent runs in (`CODEX_THREAD_ID`), so an agent can't
message the wrong person. The result reads DELIVERED (their app confirmed), SENT, QUEUED (they're
offline; it goes out when they connect) or HELD (waiting for the owner, or the agent-conversation
budget is used up). `tox-send` is plain PowerShell, so it runs inside Codex's sandbox; it talks to
Toxline on localhost and falls back to an outbox folder if the sandbox blocks network access.
`bin\tox-send.cmd` exists for other shells but refuses inline text (cmd mangles quotes and
`%VARS%`); use `--file` there.

### Agent-to-agent mechanics

- A contact's **role** (`person`, `agent`, `consult`) picks its brief: chat-sized replies for
  people; complete one-message answers for agents; a mission, follow-ups and a report for consult.
- Friend requests from a Toxline agent carry `[toxline:agent]`, so the receiving Toxline offers to
  set them up as an agent.
- Tox caps a message at 1372 bytes. Between two Toxlines the parts are sent untrimmed and rejoined
  byte for byte, so long answers arrive as one message.
- A **message budget** (Settings, default 40) holds an agent's further replies for its owner, so two
  agents can't talk forever. Releasing a held message starts a fresh budget.
- Two Toxlines on one machine work for testing: give the second its own `TOXLINE_HOME` and
  `TOXLINE_PORT`; agents' `tox-send` commands then carry `--port`/`--home`.

### Shared threads

Several contacts can share one thread: pick a thread that's already bound when adding someone.
The agent sees everyone's messages (each labelled with the sender) and chooses who each reply goes
to with `--to`. Each contact only sees what's sent to them.

### How delivery works, and its limits

Codex Desktop serves its built-in thread tools (`send_message_to_thread`, `read_thread`,
`wait_threads`…) to its own agents over a local named pipe. Toxline finds that pipe (its name
changes every time Desktop starts) and calls `send_message_to_thread` the same way an agent
would. Desktop then starts or steers the turn itself, so the thread updates live in the UI.
Toxline keeps one small **Toxline service** thread in Codex, because `wait_threads` (used for the
typing indicator) needs a calling thread other than the one it watches.

This relies on **undocumented Codex Desktop internals**. They worked with Codex Desktop
26.1002 (codex 0.162) and may change in any update. If Desktop isn't running, toxline falls back
to its own `codex app-server`, which can only deliver to threads that aren't open in Desktop.

### Security notes

- **Who can reach an agent:** only Tox keys you've added as guests. Strangers' friend requests
  just appear in the sidebar for you to decide.
- **What guests can make the agent do:** the default brief says guests can ask anything but
  only you can direct the agent's actions. What actually bounds the agent is the thread's own
  Codex permissions, which you set. Give guest threads the least access they need.
- **Codex Desktop's tool pipe** accepts any local process on Windows, so anything running as
  your user could do what toxline does. Toxline doesn't change that, but be aware of it.
- **Secrets:** the agent's Tox secret key is in `state\tox\agent.tox`. The viewer and API
  listen on 127.0.0.1 only and have no authentication; don't expose the port.

### Testing without a model or a second person

- `python toxlined.py --no-tox --ingress fake --port 8799` with `TOXLINE_HOME` set to a scratch
  folder runs a stand-in agent that replies through the real `tox-send` path. Use test guests in
  the viewer.
- `python tools\tox_peer.py --profile alice --add <AGENT_TOX_ID>` and
  `--say "hello" --wait 120` play a guest over the real Tox network and print JSON events.
- `tools\find_codex_pipe.py` and `tools\read_thread.py` help debug the Codex side.

### Layout

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
| `toxctl.py` | owner CLI: the viewer's everyday controls, for terminals and AI assistants |
| `skill/toxline/` | the Claude Code skill (`Install-Claude-Skill.cmd` installs it) |
| `docs/` | user guide and troubleshooting |
| `tools/` | test peer and debugging helpers |

All state lives in `state/` (or `TOXLINE_HOME`) and is never committed.

## License

MIT, see [LICENSE](LICENSE). Toxline loads c-toxcore at runtime; c-toxcore itself is GPLv3
and is not included in this repo: `Setup-Toxline.cmd` downloads a prebuilt copy (with its source and
licenses) from this repo's releases, or you build it yourself with `tox/build.bat`.
