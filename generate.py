#!/usr/bin/env python3
"""Render the Lakers lock-screen wallpaper to a PNG."""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lakerscreen import assets
from lakerscreen.config import DEVICES, Config
from lakerscreen.render import build


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-o", "--out", default="out/wallpaper.png", help="output PNG path")
    p.add_argument("-d", "--device", default="iphone-17-pro",
                   choices=sorted(DEVICES), help="iPhone model (sets pixel size)")
    p.add_argument("--size", help="explicit WxH in pixels, overrides --device")
    p.add_argument("-m", "--month", help="YYYY-MM to render (default: current month)")
    p.add_argument("--tz", default="America/Los_Angeles", help="timezone for tip-off times")
    p.add_argument("--team", default="lal", help="ESPN team slug")
    p.add_argument("--bg", help="background photo (cover-cropped); default is synthetic water")
    p.add_argument("--scrim", type=float, default=0.34,
                   help="0-1 darkening behind the grid for legibility")
    p.add_argument("--no-scores", action="store_true",
                   help="show a bare W/L instead of W plus the final score")
    p.add_argument("--wordmark", help="PNG of your own wordmark instead of the ESPN-derived one")
    p.add_argument("--logo-width", type=float, default=None,
                   help="wordmark width as a fraction of screen width (default 0.235)")
    p.add_argument("--show-month", action="store_true", help="print the month name above the wordmark")
    p.add_argument("--playoff-record", action="store_true",
                   help="count playoff games in the record (default: regular season only)")
    p.add_argument("--font", help="path to a .ttf/.otf to use instead of the system font")
    p.add_argument("--font-index", type=int, default=0, help="face index inside a .ttc")
    p.add_argument("--font-variation", help='named instance in a variable font, e.g. "Bold"')
    p.add_argument("--ttl", type=int, default=900,
                   help="seconds to reuse cached ESPN data (0 = always refetch)")
    p.add_argument("-q", "--quiet", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.font:
        assets.set_font(args.font, args.font_index, args.font_variation)

    size = None
    if args.size:
        try:
            w, h = args.size.lower().split("x")
            size = (int(w), int(h))
        except ValueError:
            raise SystemExit("--size must look like 1179x2556")

    cfg = Config(
        device=args.device, size=size, timezone=args.tz, team=args.team,
        background=args.bg, show_scores=not args.no_scores, scrim=args.scrim,
        month=args.month, wordmark_path=args.wordmark, show_month=args.show_month,
        record_includes_postseason=args.playoff_record,
    )
    if args.logo_width:
        cfg.layout.wordmark_width = args.logo_width

    img, month_key, shown, record = build(cfg, ttl=args.ttl)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, "PNG", compress_level=6)

    if not args.quiet:
        done = sum(1 for g in shown if g.completed)
        print("%s  %d games (%d played)  record %d-%d  %dx%d" % (
            month_key, len(shown), done, record[0], record[1], img.width, img.height))
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
