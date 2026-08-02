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
import http.server
import json
import os
from pathlib import Path
import socketserver
import sys
import webbrowser
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "edge" / "runs"
TOOLS_DIR = ROOT / "edge" / "tools"
PORT = 8080

sys.path.insert(0, str(TOOLS_DIR))
from render_dashboard import generate_dashboard_html, get_dashboard_data, analyze_symbol_adhoc
from check_gcp_resources import get_all_gcp_resources

class DashboardRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress standard noisy access log lines

    def send_json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
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
            # Allow trigger via GET or POST for convenience
            html = generate_dashboard_html()
            dashboard_path = RUNS_DIR / "dashboard.html"
            with open(dashboard_path, "w", encoding="utf-8") as f:
                f.write(html)
            self.send_json_response({"status": "ok", "message": "Pre-market scan triggered successfully."})
            return
        elif path == "/" or path == "/dashboard":
            self.path = "/dashboard.html"

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/trigger_scan":
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
    print(f"  Opening in browser...")
    print("=" * 70)

    server = None
    for port_candidate in range(PORT, PORT + 10):
        try:
            server = ThreadedHTTPServer(("", port_candidate), DashboardRequestHandler)
            if port_candidate != PORT:
                print(f"Port {PORT} was busy. Using port {port_candidate} instead.")
                print(f"URL: http://localhost:{port_candidate}/dashboard.html")
            break
        except OSError as e:
            if e.errno == 48:
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
