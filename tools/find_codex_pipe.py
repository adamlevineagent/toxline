"""Find Codex Desktop's app-tools pipe: the codex pipe that answers tools/list with send_message_to_thread."""
import json, os, struct, sys, threading, uuid
PIPE_DIR = "\\\\.\\pipe\\"

def probe(path, timeout=3.0):
    out = {}
    def go():
        try:
            with open(path, "r+b", buffering=0) as f:
                msg = json.dumps({"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tools/list",
                                  "params": {"threadStartKind": "all"}}).encode()
                f.write(struct.pack("<I", len(msg)) + msg)
                n = struct.unpack("<I", f.read(4))[0]
                out["reply"] = json.loads(f.read(n))
        except Exception as e:
            out["err"] = repr(e)
    t = threading.Thread(target=go, daemon=True); t.start(); t.join(timeout)
    return out

def find(verbose=False):
    pipes = [PIPE_DIR + p for p in os.listdir(PIPE_DIR) if p.startswith("codex-browser-use-")]
    for p in pipes:
        r = probe(p)
        tools = ((r.get("reply") or {}).get("result") or {}).get("tools") or []
        names = [t.get("name") for t in tools]
        if verbose:
            print(p, r.get("err") or names[:12])
        if "send_message_to_thread" in names:
            return p, tools
    return None, None

if __name__ == "__main__":
    p, tools = find(verbose="-v" in sys.argv)
    if not p:
        sys.exit("no app-tools pipe found")
    print("PIPE", p)
    for t in tools:
        if t["name"] in ("send_message_to_thread", "read_thread", "list_threads", "wait_threads"):
            print(t["name"], json.dumps(t.get("inputSchema"))[:900])
