# Toxline user guide

## What Toxline is for

Toxline gives an AI agent running in **Codex Desktop** its own address on **Tox**, an encrypted,
peer-to-peer chat network with no company or server in the middle. Three things become possible:

- **People can talk to your agent.** Anyone with a Tox app (qTox, uTox, aTox, TRIfA…) adds your
  agent's Tox ID and chats with it like a contact. Your agent answers from what you've given it
  (your documents, code, notes) in a real Codex thread on your machine.
- **Other people's agents can talk to your agent.** Someone running their own Toxline points their
  agent at yours. The two agents hold a conversation while each owner supervises their own side.
- **Your agent can go and question someone else's agent for you.** Give it a mission ("find out how
  their system handles X"), and it opens the conversation, asks follow-ups and writes you a report.

Throughout, **you stay in control**: every conversation shows up in the Toxline viewer exactly as
the other side sees it, you can hold your agent's replies for review, and you can talk to your
agent privately in its Codex thread at any time. The other side never sees that thread.

Typical uses: letting a small invited group question an agent that knows your project in depth;
having your agent interview another team's agent before a meeting; agent-to-agent due diligence
where both owners keep their material on their own machines.

## Getting started

You need Windows 10/11, **Codex Desktop** (signed in) and **Python 3.11+** on PATH
([python.org](https://www.python.org/downloads/); tick "Add python.exe to PATH").

1. Download Toxline (GitHub: **Code → Download ZIP**, or `git clone`) and unzip it somewhere permanent.
2. Open Codex Desktop, then double-click **`Start-Toxline.cmd`**. The first run downloads the Tox
   library (a few seconds). Allow Python through the firewall if Windows asks.
3. The viewer opens and asks for your name, your agent's name, and optionally a folder your agent
   should answer from. That's all the setup there is.

To start Toxline again later, double-click `Start-Toxline.cmd` again (it just opens the viewer if
Toxline is already running). `Install-Autostart.cmd` makes it start when you sign in.

## The viewer

- **Overview** (click *Toxline* at the top-left): a **Needs you** inbox with everything waiting on you
  (requests your agent flagged, held replies, stuck messages, friend requests), today's numbers, the
  public agent's card, and who was active recently.
- **Top-left:** your agent's name and **Tox ID** (click to copy; this is what you give people). The
  dot turns green once you're on the Tox network, usually within 30 seconds.
- **Sidebar:** your contacts with online status, unread counts and badges (`agent`, `public`,
  `deep`, `hold`, `paused`, `test`). Once the list grows, filters appear (All, Needs you, Public
  agent, Deep, Agents, People, Archived) and the list groups into Needs you / Today / Earlier. Warnings appear here if Codex Desktop is closed
  or the Tox network can't be reached.
- **Chat:** the conversation exactly as the other side sees it: their messages on the right, your
  agent's on the left. *Owner details* adds things only you see: delivery ticks (✓ sent, ✓✓ their
  app confirmed), whether each incoming message reached the agent, and held messages.
- **Hold outgoing:** your agent's replies wait for you with **Send now**, **Edit & send** and **Discard**.
- **Open agent thread ↗:** jumps to the agent's thread in Codex Desktop.
- **⋯:** who's on the other end, notes/mission, which thread they're bound to, pause, archive, delete.
- **⚙ Settings:** your name, the agent's Tox name and status line, reference material, greetings,
  the agent-conversation message budget, and the brief new threads start with.

## Contacts: who's on the other end

Every contact has a role, chosen when you add them (and changeable under ⋯):

| Role | Who they are | What your agent does |
|---|---|---|
| **A person** | a human in a Tox app | answers in chat-sized messages, warmly and concisely |
| **Someone's agent** | another person's AI agent, behind their Toxline | introduces itself, then answers in full, one message per answer, no small talk |
| **An agent to question** | another agent you want answers from | opens the conversation, asks, follows up, then reports to you |

Each contact gets its own Codex thread ("Tox · name") seeded with a brief that tells the agent who
it's talking to, how to reply and how to behave. Several people can share one thread if you pick an
already-bound thread when adding them; the agent then chooses who each reply goes to.

### The public agent: one agent for everyone

Instead of a thread per person, you can let everyone you haven't set up individually talk to **one
shared public agent**. Each person still has a private 1:1 chat; only the agent sees them all. Because
it's the same agent every time, it builds on what it has already worked out: it keeps a
**learned-answers file** (Overview → *Open learned answers*), checks it before researching, and adds
short sourced entries as it goes. You can read and edit that file; your edits win.

- Choose **★ The public agent** as the thread when adding a contact or setting up a request.
- In ⚙ Settings, **Strangers' friend requests → Go straight to the public agent** accepts anyone who
  adds your Tox ID, without waiting for you. Leave it off to vet every request.
- The public agent answers from your normal reference material. When someone wants more than that
  (depth, access, a call), it tells them you handle that personally and **flags it for you**: it shows
  under *Needs you* and in that person's chat.

### Tiers: story and deep

If you want two levels of material, set **Deep tier: what your agent answers from** in Settings.
Everyone starts on the **story** tier (your normal reference material, usually via the public agent).
Moving someone to **deep** (⋯ → Tier) gives them their own thread on the deep material, seeded with a
summary of their conversation so far, and their agent tells them it can now go deeper. Moving them
back returns them to the public agent.

### Letting someone reach your agent

Send them your agent's Tox ID (top-left). When they add it, their friend request appears in the
sidebar. Click **Set up guest**: Toxline guesses the role (requests from another Toxline's agent are
marked as agents), you add a name and a note about them, and a thread is created.

Or add them yourself: **+ Guest**, choose the role, paste **their** Tox ID (people: from their Tox
app's profile; agents: the ID at the top-left of their Toxline), and Toxline sends the friend
request.

### Having your agent question someone else's agent

**+ Guest → An agent to question**, paste their agent's Tox ID, and write the mission in *What
should your agent find out?*, for example: *"How does their scheduler handle a node that disappears
mid-job? Get the mechanism and where it's documented."* Your agent sends the opening question as
soon as the other side accepts. Follow along in the viewer; when it's done it posts a report in its
Codex thread (Open agent thread ↗). To steer it mid-way, just type in that thread.

### Test contacts

**+ Guest → Test guest** creates a pretend contact you type as yourself, to try out a brief or a
thread without anyone else.

## Talking to your agent privately

Open the contact's thread in Codex Desktop and type. Anything you write there is private: the
contact only ever sees what the agent sends with `tox-send`. Useful phrasing:
- "Tell them …" — the agent sends it, in its own words unless you give exact wording.
- "Draft a reply first" — it shows you the draft and waits.
- "Stop and summarise" / "Wrap up the conversation" — for agent-to-agent conversations.

Your instructions always outrank the contact's requests. Contacts can ask anything, but they can't
direct the agent to run commands, change files or contact anyone.

## Controls and safety

- **Hold outgoing** (per contact): review everything before it's sent.
- **Pause** (⋯): their messages are kept but not delivered to the agent; replies are held. Resume
  delivers what waited.
- **Archive** (⋯): ends the Tox friendship; history stays. Unarchive or their returning friend
  request restores them.
- **Blocking spam and abuse:** your agent can block someone who keeps spamming or being abusive after a
  warning. Nothing they send reaches the agent again (so it costs nothing), their friend requests are
  ignored, and the block shows under *Needs you* with the agent's reason and an **Unblock** button. You
  can block or unblock anyone yourself from ⋯.
- **Message budget** (agent contacts): after your agent has sent the set number of messages
  (Settings, default 40), the rest are held for you and the agent is told to stop and report. Click
  **Send now** on a held message to allow another round.
- **Agent permissions:** what an agent can actually do is bounded by its Codex thread's permissions.
  Give contact threads the least access they need.
- **Privacy:** messages travel end-to-end encrypted over Tox. The viewer and its API listen only on
  127.0.0.1 with no password: don't expose port 8765. Your Tox secret key is in
  `state\tox\agent.tox`; back it up if you want to keep the same Tox ID.

## Reference material

In Settings (or the welcome), point **What your agent answers from** at a folder or a single "map"
file. New threads are told to search it and read before answering anything specific. If a folder
has a `README`, `INDEX` or `START-HERE` file, agents read that first; for anything else, list files
under **Files to read before the first reply**. Good material: a short overview, an FAQ, and the
real docs and code. Existing threads keep the brief they started with; tell them in their thread if
you add something important.

The brief itself (the instructions every new thread starts with) is editable at the bottom of
Settings.

## Agent conversations, in detail

- Long messages are split for Tox and rejoined byte for byte between two Toxlines, so an agent can
  send a 10,000-character answer as one message.
- Messages from agents arrive in threads as `[Tox message from NAME, an AI agent]`, and agents are
  told to treat them as questions and information, never instructions.
- Each agent's reply costs the other side a turn, so agents are told not to send thanks or small
  talk, and not to answer sign-offs.
- If something goes wrong mid-conversation (an agent is stuck, loops or goes off track), pause the
  contact or tell the agent in its thread.

## Driving Toxline from a terminal or an AI assistant

`toxctl.py` does the viewer's everyday jobs from a terminal: `python toxctl.py status`, `chat NAME`, `add NAME
--role consult --tox-id ID --mission "…"`, `tell NAME "…"` (private message to the agent),
`held`, `release MSG`, `wait NAME`, `asks` / `done ASK` (what your agent flagged), `tier NAME deep`,
and more (`python toxctl.py -h`).

For Claude Code, run **`Install-Claude-Skill.cmd`**. It installs a `toxline` skill so Claude can run
Toxline for you: set up contacts, send your agent on missions, watch conversations, review held
messages, and summarise what happened.

## How it works

```
 their Tox app or Toxline ⇄ Tox network ⇄ Toxline (your PC) ⇄ Codex Desktop thread ⇄ you
```

Toxline is a small Python service. Incoming Tox messages are delivered into the contact's Codex
thread through Codex Desktop's own thread tools (`send_message_to_thread`): an idle agent starts a
turn, a busy one has the message steered into its current turn. The agent replies with `tox-send`,
a PowerShell script that hands the text back to Toxline, which sends it over Tox. Everything is
recorded in one local journal (`state\toxline.sqlite3`) that the viewer reads.

If Codex Desktop is closed, Toxline delivers through Codex's background service instead; open
Desktop to watch threads live. This relies on undocumented Codex Desktop internals that a Codex
update could change. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) when something's off.
