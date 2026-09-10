"""Isolated upstream fixture for the Caddy TLS smoke check; never an app service."""

from http.server import BaseHTTPRequestHandler, HTTPServer


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()
        self.wfile.write(b"upstream-health-fixture")


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), HealthHandler).serve_forever()
