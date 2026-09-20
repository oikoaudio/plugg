"""A loopback HTTP server for download tests.

Downloads are only meaningful to test against a real HTTP client, because the
policy under test is about schemes, hosts and redirects. Nothing here reaches
the network: the server binds 127.0.0.1 on an ephemeral port.
"""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


@contextlib.contextmanager
def serve(files, redirects=None, host='127.0.0.1'):
    """Serve ``{path: bytes}`` and ``{path: location}`` on loopback."""
    redirects = redirects or {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in redirects:
                self.send_response(302)
                self.send_header('Location', redirects[self.path])
                self.end_headers()
                return
            body = files.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer((host, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://{host}:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
