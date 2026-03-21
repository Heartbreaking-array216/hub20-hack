#!/usr/bin/env python3
"""
Mini servidor local que serve o HTML e faz proxy das chamadas API do Hub 2.0.
Necessário porque a API não tem headers CORS.

Uso: python3 server.py
Abre: http://localhost:8080
"""

import http.server
import json
import os
import urllib.request
import urllib.error
from urllib.parse import urlparse

PORT = 8080
TARGETS = {
    "/proxy/accounts": "https://api-accounts.hubert.com.br",
    "/proxy/morador": "https://api-morador.hubert.com.br",
}


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/proxy/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/proxy/"):
            self._proxy("POST")
        else:
            self.send_error(405)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Origin")

    def _proxy(self, method: str):
        # Resolve target URL
        target_url = None
        api_path = ""
        for prefix, base in TARGETS.items():
            if self.path.startswith(prefix):
                api_path = self.path[len(prefix):]
                target_url = base + api_path
                break

        if not target_url:
            self.send_error(404, "Proxy target not found")
            return

        # Read request body
        body = None
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            body = self.rfile.read(content_length)

        # Build upstream request
        req = urllib.request.Request(target_url, data=body, method=method)

        # Forward relevant headers
        for header in ["Authorization", "Content-Type"]:
            val = self.headers.get(header)
            if val:
                req.add_header(header, val)

        # Always set Origin to app-morador (browser overrides Origin header)
        req.add_header("Origin", "app-morador")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                self._cors_headers()
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            self.send_response(e.code)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as e:
            self.send_response(502)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, fmt, *args):
        # Colorir logs
        msg = fmt % args
        if "POST" in msg and "proxy" in msg:
            print(f"  🔄 {msg}")
        elif "GET" in msg and "proxy" in msg:
            print(f"  📡 {msg}")
        elif "200" in msg or "204" in msg:
            print(f"  ✅ {msg}")
        elif "400" in msg or "401" in msg or "500" in msg:
            print(f"  ❌ {msg}")
        else:
            print(f"  {msg}")


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    server = http.server.HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"""
╔══════════════════════════════════════════╗
║       🏢 HUB 2.0 - LOCAL SERVER ⚡      ║
╚══════════════════════════════════════════╝
  🌐 http://localhost:{PORT}
  📁 Servindo: {os.getcwd()}
  ⏹️  Ctrl+C para parar
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor parado.")
        server.server_close()


if __name__ == "__main__":
    main()
