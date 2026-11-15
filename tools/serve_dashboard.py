#!/usr/bin/env python3
"""Local Dashboard Multi-Threaded HTTP Server & Live REST API Backend.

Serves `edge/runs/dashboard.html` and REST API endpoints at `http://localhost:8080`.

API Endpoints:
  - GET  /api/status            : Full dashboard state payload (JSON)
  - GET  /api/pead_candidates   : Active pre-market PEAD gap setups (JSON)
  - GET  /api/gcp_resources     : Vertex AI jobs, Cloud Run, GCS storage, Webhooks, Credit status (JSON)
  - GET  /api/leaderboard       : Model gate evaluation leaderboard (JSON)
  - POST /api/trigger_scan      : Triggers instant live pre-market scan & updates dashboard (JSON)

Usage:
  python3 edge/tools/serve_dashboard.py
"""
import errno
import http.server
import json
import os
from pathlib import Path
import socketserver
import sys
import webbrowser
from urllib.parse import parse_qs, urlparse

# The live API is loopback-only (see tools/api_server.py). This older server
# used to listen on every interface and send a wildcard CORS header, so a
# page on another origin could read local run artifacts and fire the scan.
LOOPBACK_HOST = "127.0.0.1"
_LOOPBACK_NAMES = frozenset({"127.0.0.1", "::1", "localhost"})

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "edge" / "runs"
TOOLS_DIR = ROOT / "edge" / "tools"
PORT = 8080

sys.path.insert(0, str(TOOLS_DIR))
from render_dashboard import generate_dashboard_html, get_dashboard_data, analyze_symbol_adhoc
from check_gcp_resources import get_all_gcp_resources


def host_is_loopback(host: str | None) -> bool:
    if not host:
        return False
    return host.strip().lower().split("%", 1)[0] in _LOOPBACK_NAMES


def origin_is_loopback(origin: str | None) -> bool:
    """Missing Origin is a non-browser client. A browser Origin must be loopback."""
    if origin is None or not str(origin).strip():
        return True
    return host_is_loopback(urlparse(str(origin)).hostname)


class DashboardRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress standard noisy access log lines

    def send_json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refuse_remote(self) -> bool:
        client = self.client_address[0] if self.client_address else ""
        if host_is_loopback(client):
            return False
        self.send_json_response({"error": "loopback only"}, status=403)
        return True

    def _refuse_cross_origin_trigger(self) -> bool:
        if origin_is_loopback(self.headers.get("Origin")):
            return False
        self.send_json_response({"error": "cross-origin trigger refused"}, status=403)
        return True

    def do_GET(self):
        if self._refuse_remote():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/status":
            self.send_json_response(get_dashboard_data())
            return
        elif path == "/api/analyze":
            symbol = query.get("symbol", [""])[0]
            self.send_json_response(analyze_symbol_adhoc(symbol))
            return
        elif path == "/api/pead_candidates":
            data = get_dashboard_data()
            self.send_json_response({"asof": data["asof"], "candidates": data["pead_candidates"]})
            return
        elif path == "/api/gcp_resources":
            self.send_json_response(get_all_gcp_resources())
            return
        elif path == "/api/leaderboard":
            data = get_dashboard_data()
            self.send_json_response({"asof": data["asof"], "leaderboard": data["leaderboard"]})
            return
        elif path == "/api/trigger_scan":
            # State change stays on POST. A GET would run from an <img> on
            # another origin even after the bind is loopback.
            self.send_json_response(
                {"error": "use POST /api/trigger_scan"},
                status=405,
            )
            return
        elif path == "/" or path == "/dashboard":
            self.path = "/dashboard.html"

        return super().do_GET()

    def do_POST(self):
        if self._refuse_remote():
            return
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/trigger_scan":
            if self._refuse_cross_origin_trigger():
                return
            html = generate_dashboard_html()
            dashboard_path = RUNS_DIR / "dashboard.html"
            with open(dashboard_path, "w", encoding="utf-8") as f:
                f.write(html)
            self.send_json_response({"status": "ok", "message": "Pre-market scan triggered successfully."})
            return

        self.send_json_response({"error": "Endpoint not found"}, status=404)

class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

def main():
    print("Generating latest dynamic dashboard...")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    html = generate_dashboard_html()
    dashboard_path = RUNS_DIR / "dashboard.html"
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(html)

    os.chdir(RUNS_DIR)

    print("=" * 70)
    print("  TRADING ENGINE DASHBOARD SERVER (DYNAMIC REST API ACTIVE)")
    print("=" * 70)
    print(f"  URL:           http://localhost:{PORT}/dashboard.html")
    print(f"  API Status:    http://localhost:{PORT}/api/status")
    print(f"  API GCP:       http://localhost:{PORT}/api/gcp_resources")
    print("  Opening in browser...")
    print("=" * 70)

    server = None
    for port_candidate in range(PORT, PORT + 10):
        try:
            server = ThreadedHTTPServer((LOOPBACK_HOST, port_candidate), DashboardRequestHandler)
            if port_candidate != PORT:
                print(f"Port {PORT} was busy. Using port {port_candidate} instead.")
                print(f"URL: http://127.0.0.1:{port_candidate}/dashboard.html")
            break
        except OSError as e:
            # 48 is EADDRINUSE on macOS; Linux uses 98. errno.EADDRINUSE covers both.
            if e.errno == errno.EADDRINUSE:
                continue
            raise

    if server is None:
        print(f"Error: Could not bind to any port in range {PORT}-{PORT+9}.")
        sys.exit(1)

    try:
        webbrowser.open(f"http://localhost:{server.server_address[1]}/dashboard.html")
    except Exception:
        pass

    try:
        with server:
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")

if __name__ == "__main__":
    main()
