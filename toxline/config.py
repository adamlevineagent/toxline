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
    "library_map": "",                    # a file the agents should start from when researching
    "greeting": "Hi {name}, this is {guide_name}. Accept to start chatting.",
}


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
