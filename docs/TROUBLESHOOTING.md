# Troubleshooting

Start with `python toxctl.py status` (or the viewer's sidebar warnings). The service log is
`state\toxline.log`.

**Start-Toxline says Python isn't installed.** Install Python 3.11+ from python.org and tick "Add
python.exe to PATH", then run `Start-Toxline.cmd` again. If you installed it but it still isn't
found, sign out and back in (PATH changes need a new session).

**"Toxline didn't start."** Start-Toxline prints the end of `state\toxline.log`. Common causes:
- *Can't load the Tox library … vcruntime140.dll:* install the Microsoft Visual C++ Redistributable
  (x64): https://aka.ms/vs/17/release/vc_redist.x64.exe
- *Port 8765 is in use:* another Toxline is already running (Start-Toxline would just open it), or
  another program uses the port. To run on another port: `set TOXLINE_PORT=8766` then start.
- *Download failed:* check your internet connection; `Setup-Toxline.cmd` retries the download and
  runs a full check.

**The dot at the top-left stays grey** (not on the Tox network after a minute). Allow Python in
Windows Firewall (Settings → Privacy & security → Windows Security → Firewall → Allow an app), or
check that your network doesn't block outbound UDP/TCP. Tox falls back to TCP relays, so most
networks work.

**"Codex Desktop isn't open."** Open Codex Desktop. Messages still reach agents in the background
while it's closed, but you only see threads update live with Desktop open.

**A contact's messages aren't reaching the agent.** In the chat, incoming messages show their state
(with *Owner details* on): *delivering*, *in agent thread ✓*, *kept (not delivered yet)* or
*delivery to agent failed*. Use **Deliver to agent** on a stuck one. Check the contact isn't paused (⋯) and
has a thread.

**My agent's replies aren't going out.** Look for *held* messages (hold outgoing, paused contact, or
the agent-conversation budget) and use Send now. *Waiting for them to come online* means the
contact is offline; it sends automatically when they connect. In the agent's thread, `tox-send`
prints exactly what happened to each message.

**My friend request isn't accepted.** The other side has to accept it (in their Tox app, or with
Set up guest in their Toxline). Messages your agent writes meanwhile wait and go out when they do.

**Agents keep talking in circles.** Lower the agent-conversation budget in Settings, pause the
contact, or tell the agent in its thread to wrap up.

**I want the same Tox ID on a new machine.** Copy `state\tox\agent.tox` (it holds the secret key)
into the new install's `state\tox\` before first start.

**Run a full check.** `Setup-Toxline.cmd` checks Python, verifies the Tox library's checksums, runs a
two-node Tox self-test and checks Codex Desktop.
