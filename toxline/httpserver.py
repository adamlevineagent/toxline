"""Tiny stdlib HTTP + SSE server so toxline has zero third-party dependencies."""
import json
import queue
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".ico": "image/x-icon", ".json": "application/json"}


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, static_dir):
        self.routes = []
        self.static_dir = Path(static_dir)

    def route(self, method, path):
        def deco(fn):
            self.routes.append((method, path.strip("/").split("/"), fn))
            return fn
        return deco

    def match(self, method, path):
        parts = path.strip("/").split("/")
        for m, pattern, fn in self.routes:
            if m != method or len(pattern) != len(parts):
                continue
            params = {}
            for p, v in zip(pattern, parts):
                if p.startswith(":"):
                    params[p[1:]] = v
                elif p != v:
                    break
            else:
                return fn, params
        return None, None

    def serve(self, host, port):
        app = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                if not n:
                    return {}
                raw = self.rfile.read(n)
                try:
                    return json.loads(raw.decode("utf-8"))
                except ValueError:
                    raise HttpError(400, "body must be JSON")

            def _send(self, status, payload, ctype="application/json"):
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _handle(self, method):
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                fn, params = app.match(method, url.path)
                try:
                    if fn is None:
                        if method == "GET":
                            return self._static(url.path)
                        raise HttpError(404, "no route")
                    body = self._body() if method == "POST" else {}
                    result = fn(req=self, query=query, body=body, **params)
                    if result is STREAMED:
                        return
                    self._send(200, result if result is not None else {"ok": True})
                except HttpError as e:
                    self._send(e.status, {"error": str(e)})
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                except Exception as e:
                    traceback.print_exc()
                    try:
                        self._send(500, {"error": f"{type(e).__name__}: {e}"})
                    except Exception:
                        pass

            def _static(self, path):
                rel = path.lstrip("/") or "index.html"
                f = (app.static_dir / rel).resolve()
                if app.static_dir.resolve() not in f.parents or not f.is_file():
                    f = app.static_dir / "index.html"   # SPA fallback
                self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def sse(self, q, initial=None):
                """Stream events from queue q as text/event-stream until the client leaves."""
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    for ev in initial or []:
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            ev = q.get(timeout=15)
                            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
                return STREAMED

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                import sys
                if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
                    return   # clients dropping keep-alive connections; not an error
                super().handle_error(request, client_address)

        server = Server((host, port), Handler)
        t = threading.Thread(target=server.serve_forever, name="http", daemon=True)
        t.start()
        return server


STREAMED = object()
