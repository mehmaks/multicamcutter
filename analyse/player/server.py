"""Analyse-Player — lokaler Server (nur 127.0.0.1, nur Standardbibliothek).

  GET  /                 player.html
  GET  /s/<datei>        Dateien des Sitzungsordners (mit Range — nötig zum Springen im Ton)
  GET  /api/labels       Bewertungen (labels.json im Sitzungsordner)
  POST /api/labels       Bewertungen speichern (atomar, mit Zeitstempel)

Aufruf: venv/bin/python3 analyse/player/server.py SITZUNGSORDNER [--port 8765]
"""
import argparse
import json
import mimetypes
import os
import re
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HTML = Path(__file__).resolve().parent / "player.html"
SESSION: Path = Path(".")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/labels":
            p = SESSION / "labels.json"
            return self._send(200, p.read_bytes() if p.exists() else b"{}")
        if self.path.startswith("/s/"):
            name = self.path[3:].split("?")[0]
            p = (SESSION / name).resolve()
            if SESSION not in p.parents or not p.is_file():
                return self._send(404, b"nicht gefunden", "text/plain")
            return self._file(p)
        self._send(404, b"nicht gefunden", "text/plain")

    def _file(self, p):
        size = p.stat().st_size
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".m4a":
            ctype = "audio/mp4"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = size - int(m.group(2))
            end = min(end, size - 1)
            code = 206
        else:
            code = 200
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(p, "rb") as f:
            f.seek(start)
            left = length
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_POST(self):
        if self.path != "/api/labels":
            return self._send(404, b"{}")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            data = json.loads(body)
        except ValueError:
            return self._send(400, b'{"fehler":"kein JSON"}')
        data["gespeichert"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = SESSION / "labels.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, SESSION / "labels.json")
        self._send(200, json.dumps({"ok": True, "gespeichert": data["gespeichert"]}).encode())


def main():
    global SESSION
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    SESSION = Path(a.session).resolve()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"Analyse-Player: http://127.0.0.1:{a.port}  (Sitzung {SESSION})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
