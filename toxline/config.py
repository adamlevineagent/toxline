"""Owner settings: names and wording that make a toxline install yours.

Stored in <TOXLINE_HOME>/config.json; editable from the viewer's Settings.
"""
import json

from . import db as dbmod

DEFAULTS = {
    "owner": "the owner",                 # how agents and guests refer to you
    "guide_name": "Toxline Guide",        # the agent's Tox display name
    "status_message": "Ask me anything",  # the agent's Tox status line
    "topic": "",                          # what guests come to learn about (optional)
    "library_map": "",                    # a folder (or a map file) agents answer from; optional
    "read_first": "",                     # files agents read before their first reply (; separated)
    "greeting": "Hi {name}, this is {guide_name}. Accept to start chatting.",
    # Friend request your agent sends when it reaches out to someone else's agent. The tag at
    # the end lets their Toxline recognise an agent and set it up as one.
    "agent_greeting": "Hi, this is {guide_name}, an AI agent reaching out for {owner} through Toxline. " + "[toxline:agent]",
    # Agent-to-agent conversations: how many messages your agent may send before the rest are
    # held for you (stops two agents talking forever). Releasing a held one allows this many more.
    "agent_budget": "40",
}

AGENT_TAG = "[toxline:agent]"


def agent_budget():
    try:
        return max(1, int(load()["agent_budget"]))
    except (TypeError, ValueError):
        return int(DEFAULTS["agent_budget"])


def reference(role="person"):
    """How a new thread should use the owner's reference material: (brief text, files to read first)."""
    from pathlib import Path
    cfg = load()
    lib = (cfg.get("library_map") or "").strip().strip('"')
    if role == "consult":
        return "Ground your answers in what you can actually read and verify.\n", []
    first = [Path(x.strip().strip('"')) for x in (cfg.get("read_first") or "").split(";") if x.strip()]
    if not lib:
        return "Ground your answers in what you can actually read and verify.\n", [f for f in first if f.exists()]
    p = Path(lib)
    if p.is_dir():
        if not first:
            first = sorted(q for q in p.iterdir() if q.is_file() and q.stem.lower() in ("readme", "index", "start-here"))[:2]
        text = (f"Ground your answers in the reference material under `{p}`. Search it (rg works well) and "
                f"read the relevant files before answering anything specific.\n")
    else:
        first = first or [p]
        text = (f"Ground your answers in the reference material. Start from `{p}` and read "
                f"before answering anything specific.\n")
    return text, [f for f in first if f.exists()]


def path():
    return dbmod.HOME / "config.json"


def load():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save(updates):
    cfg = load()
    for k, v in updates.items():
        if k in DEFAULTS and isinstance(v, str):
            cfg[k] = v.strip()
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def fill(text, **extra):
    """Fill {owner}, {guide_name}, {topic}, ... placeholders without choking on other braces."""
    values = dict(load(), **extra)
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text
