#!/usr/bin/env python3
"""Serve the wallpaper over HTTP so an iOS Shortcut can fetch it.

    GET /wallpaper.png[?device=&month=&tz=]   the image
    GET /                                     status page
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lakerscreen.config import DEVICES, Config
from lakerscreen.render import build

CACHE = {}
CACHE_LOCK = threading.Lock()
OPTS = argparse.Namespace()


def render_png(device: str, month, tz: str) -> bytes:
    """Render (or reuse) a PNG. Cached per distinct request for --refresh secs."""
    key = (device, month, tz)
    now = time.time()
    with CACHE_LOCK:
        hit = CACHE.get(key)
        if hit and now - hit[0] < OPTS.refresh:
            return hit[1]

    cfg = Config(device=device, month=month, timezone=tz, team=OPTS.team,
                 background=OPTS.bg, background_align=OPTS.bg_align,
                 show_scores=not OPTS.no_scores, scrim=OPTS.scrim,
                 wordmark_path=OPTS.wordmark, show_month=OPTS.show_month,
                 record_includes_postseason=OPTS.playoff_record,
                 single_column_max=OPTS.single_column_max)
    img, month_key, shown, record = build(cfg, ttl=OPTS.refresh)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    data = buf.getvalue()

    with CACHE_LOCK:
        CACHE[key] = (now, data, month_key, len(shown), record)
    print("[%s] rendered %s  %d games  %d-%d  %.0f KB" % (
        time.strftime("%H:%M:%S"), month_key, len(shown), record[0], record[1], len(data) / 1024))
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quieter than the default access log
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)

        if parsed.path in ("/wallpaper.png", "/wallpaper", "/w"):
            device = q.get("device", [OPTS.device])[0]
            if device not in DEVICES:
                self.send_error(400, "unknown device %r" % device)
                return
            month = q.get("month", [None])[0]
            tz = q.get("tz", [OPTS.tz])[0]
            try:
                data = render_png(device, month, tz)
            except Exception as exc:
                self.send_error(500, "render failed: %s" % exc)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/":
            with CACHE_LOCK:
                rows = "".join(
                    "<li>%s &rarr; %s, %d games, %d-%d</li>" % (k[0], v[2], v[3], v[4][0], v[4][1])
                    for k, v in CACHE.items() if len(v) > 2
                ) or "<li>nothing rendered yet</li>"
            body = (
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<body style='font:16px -apple-system;background:#111;color:#eee;padding:2rem'>"
                "<h2>Lakers lock screen</h2>"
                "<p><a style='color:#FDB927' href='/wallpaper.png'>/wallpaper.png</a></p>"
                "<ul>%s</ul></body>" % rows
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("-d", "--device", default="iphone-17-pro", choices=sorted(DEVICES))
    p.add_argument("--tz", default="America/Los_Angeles")
    p.add_argument("--team", default="lal")
    p.add_argument("--bg")
    p.add_argument("--bg-align", default="center", choices=("top", "center", "bottom"))
    p.add_argument("--scrim", type=float, default=0.15)
    p.add_argument("--no-scores", action="store_true")
    p.add_argument("--wordmark")
    p.add_argument("--show-month", action="store_true")
    p.add_argument("--playoff-record", action="store_true")
    p.add_argument("--single-column-max", type=int, default=8)
    p.add_argument("--refresh", type=int, default=900,
                   help="seconds before a cached render is rebuilt")
    p.parse_args(namespace=OPTS)

    srv = ThreadingHTTPServer((OPTS.host, OPTS.port), Handler)
    print("serving http://%s:%d/wallpaper.png  (device=%s, refresh=%ds)"
          % (OPTS.host, OPTS.port, OPTS.device, OPTS.refresh))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
