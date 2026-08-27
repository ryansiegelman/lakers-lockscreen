"""Compose the lock-screen wallpaper: two-column game grid plus wordmark footer."""
from __future__ import annotations

import calendar
import math
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from . import assets, background
from .config import Config
from .espn import (
    Game,
    games_in_month,
    load_games,
    logo_urls,
    next_month_with_games,
    season_for,
    season_record,
)

SS = 2  # supersample factor; rounded rects alias badly at 1x

Run = Dict[str, object]


class _Canvas:
    """Draws in final-image coordinates onto a supersampled RGBA overlay."""

    def __init__(self, size: Tuple[int, int], ss: int = SS):
        self.ss = ss
        self.layer = Image.new("RGBA", (size[0] * ss, size[1] * ss), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)

    def font(self, size: float):
        return assets.load_font(int(round(size * self.ss)))

    def text_width(self, text: str, font, tracking: float = 0.0) -> float:
        return assets.tracked_width(font, text, tracking * self.ss) / self.ss

    def rounded_rect(self, box, radius, fill=None, outline=None, width=1.0):
        s = self.ss
        self.draw.rounded_rectangle(
            [box[0] * s, box[1] * s, box[2] * s, box[3] * s],
            radius=int(round(radius * s)), fill=fill, outline=outline,
            width=max(1, int(round(width * s))),
        )

    def rect(self, box, fill):
        s = self.ss
        self.draw.rectangle([box[0] * s, box[1] * s, box[2] * s, box[3] * s], fill=fill)

    def text(self, xy, text, font, fill, tracking=0.0, anchor="lc",
             stroke_width=0.0, stroke_fill=None):
        s = self.ss
        return assets.draw_tracked(
            self.draw, (xy[0] * s, xy[1] * s), text, font, fill,
            tracking_px=tracking * s, anchor=anchor,
            stroke_width=stroke_width * s, stroke_fill=stroke_fill,
        ) / s

    def paste_centered(self, img: Image.Image, center, width: float) -> float:
        s = self.ss
        im = assets.fit_width(img, width * s)
        self.layer.alpha_composite(
            im, (int(round(center[0] * s - im.width / 2.0)),
                 int(round(center[1] * s - im.height / 2.0))))
        return im.height / float(s)

    def flatten_onto(self, base: Image.Image) -> Image.Image:
        small = self.layer.resize(base.size, Image.LANCZOS)
        out = base.convert("RGBA")
        out.alpha_composite(small)
        return out.convert("RGB")


# --- run-based line layout -------------------------------------------------
# A "line" is a sequence of runs (text or colour swatch) laid out left to right
# and centred as a unit, so every chip's contents sit centred in their zone.

def _text_run(c: _Canvas, text: str, size: float, fill, tracking: float = 0.0,
              gap: float = 0.0, stroke: float = 0.0, stroke_fill=None,
              fixed_gap: bool = False) -> Run:
    font = c.font(size)
    return {"kind": "text", "text": text, "font": font, "fill": fill,
            "tracking": tracking, "gap": gap, "stroke": stroke,
            "stroke_fill": stroke_fill, "fixed_gap": fixed_gap,
            "w": c.text_width(text, font, tracking)}


def _swatch_run(width: float, height: float, fill, gap: float = 0.0) -> Run:
    return {"kind": "swatch", "h": height, "fill": fill, "gap": gap, "w": width}


def _runs_width(runs: Sequence[Run]) -> float:
    if not runs:
        return 0.0
    return sum(float(r["w"]) for r in runs) + sum(float(r["gap"]) for r in runs[:-1])


def _fit(factory: Callable[[float], List[Run]], size: float, max_w: float,
         floor: float) -> List[Run]:
    """Build a line, shrinking the type if it would overflow its zone."""
    runs = factory(size)
    total = _runs_width(runs)
    if total > max_w > 0:
        return factory(size * max(floor, max_w / total))
    return runs


def _justify(c: _Canvas, runs: List[Run], target: float) -> List[Run]:
    """Stretch a line to `target` width by opening up its letter-spacing.

    Used to make the date line and the result line exactly the same width, so
    they align flush on both edges instead of each centring independently.
    """
    natural = _runs_width(runs)
    if not runs or natural >= target:
        return runs
    # A run marked fixed_gap keeps its trailing space untouched. The W/L badge
    # uses this: otherwise every bit of slack pools into the single gap after a
    # one-glyph run and the badge drifts away from the score it belongs to.
    stretch = [i for i in range(len(runs) - 1) if not runs[i].get("fixed_gap")]
    gaps = sum(len(str(r["text"])) - 1 for r in runs if r["kind"] == "text")
    gaps += len(stretch)
    if gaps <= 0:
        return runs
    extra = (target - natural) / gaps
    for i, r in enumerate(runs):
        if r["kind"] == "text":
            r["tracking"] = float(r["tracking"]) + extra
            r["w"] = c.text_width(str(r["text"]), r["font"], float(r["tracking"]))
        if i in stretch:
            r["gap"] = float(r["gap"]) + extra
    return runs


def _draw_runs(c: _Canvas, cx: float, cy: float, runs: Sequence[Run]) -> None:
    x = cx - _runs_width(runs) / 2.0
    for i, r in enumerate(runs):
        if r["kind"] == "text":
            c.text((x, cy), r["text"], r["font"], r["fill"],
                   tracking=float(r["tracking"]), anchor="lc",
                   stroke_width=float(r.get("stroke", 0.0)),
                   stroke_fill=r.get("stroke_fill"))
        else:
            hh, ww = float(r["h"]), float(r["w"])
            c.rect((x, cy - hh / 2.0, x + ww, cy + hh / 2.0), fill=r["fill"])
        x += float(r["w"]) + (float(r["gap"]) if i < len(runs) - 1 else 0.0)


def _fmt_date(g: Game) -> str:
    return g.start_local.strftime("%a, %-m/%-d").upper()


def _fmt_time(g: Game) -> str:
    return g.start_local.strftime("%-I:%M %p").upper()


def _draw_chip(c: _Canvas, box, g: Game, cfg: Config) -> None:
    lay, pal = cfg.layout, cfg.palette
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    radius = h * lay.corner_radius_ratio
    border = h * lay.border_ratio

    # Offset twin behind the chip produces the stacked-sticker edge.
    dx, dy = h * lay.stack_dx, h * lay.stack_dy
    c.rounded_rect((x0 + dx, y0 + dy, x1 + dx, y1 + dy), radius,
                   fill=pal.chip_fill, outline=pal.chip_shadow, width=border)
    c.rounded_rect((x0, y0, x1, y1), radius,
                   fill=pal.chip_fill, outline=pal.chip_border, width=border)

    pad = w * lay.pad_x_ratio
    half_gap = w * lay.zone_gap / 2.0
    lz0, lz1 = x0 + pad, x0 + w * lay.split - half_gap
    rz0, rz1 = x0 + w * lay.split + half_gap, x1 - pad
    lcx, rcx = (lz0 + lz1) / 2.0, (rz0 + rz1) / 2.0
    lw, rw = lz1 - lz0, rz1 - rz0
    ya, yb = y0 + h * lay.line1_y, y0 + h * lay.line2_y
    floor = lay.min_shrink

    # Left zone, top line: the date.
    top_left = _fit(
        lambda s: [_text_run(c, _fmt_date(g), s, pal.text, tracking=s * lay.date_tracking)],
        h * lay.date_size, lw, floor)

    # Left zone, bottom line: tip-off time before the game, result after it.
    if g.completed and g.won is not None:
        letter = "W" if g.won else "L"
        score = g.score_line if cfg.show_scores else ""

        def bottom(s: float) -> List[Run]:
            # Outlined badge: black fill, white keyline, set smaller than the
            # score and held off it by a wider gap.
            runs = [_text_run(c, letter, s * lay.result_size, pal.result_fill,
                              gap=s * lay.result_gap,
                              stroke=s * lay.result_size * lay.result_stroke,
                              stroke_fill=pal.result_outline, fixed_gap=True)]
            if score:
                runs.append(_text_run(c, score, s, pal.text))
            return runs
    elif g.state == "in":
        live = "%d-%d" % (g.team_score, g.opp_score) \
            if g.team_score is not None and g.opp_score is not None else ""

        def bottom(s: float) -> List[Run]:
            runs = [_text_run(c, "LIVE", s, pal.live, tracking=s * 0.06, gap=s * 0.30)]
            if live:
                runs.append(_text_run(c, live, s * 0.95, pal.text_dim))
            return runs
    else:
        def bottom(s: float) -> List[Run]:
            return [_text_run(c, _fmt_time(g), s, pal.text)]

    bot_left = _fit(bottom, h * lay.time_size, lw, floor)

    # Right zone: home/away marker over the opponent's code.
    swatch = pal.gold if g.is_home else pal.purple
    top_right = _fit(
        lambda s: [_text_run(c, "vs" if g.is_home else "at", s, pal.text,
                             tracking=s * lay.vs_tracking, gap=h * lay.dot_gap),
                   _swatch_run(h * lay.dot_w, h * lay.dot_h, swatch)],
        h * lay.vs_size, rw, floor)
    bot_right = _fit(
        lambda s: [_text_run(c, g.opponent, s, pal.text, tracking=s * lay.team_tracking)],
        h * lay.team_size, rw, floor)

    # Square each pair off: both lines in a zone get the same width, so their
    # left and right edges line up.
    for pair, zone_w, cx in ((( top_left, bot_left), lw, lcx),
                             ((top_right, bot_right), rw, rcx)):
        target = min(max(_runs_width(pair[0]), _runs_width(pair[1])), zone_w)
        _draw_runs(c, cx, ya, _justify(c, list(pair[0]), target))
        _draw_runs(c, cx, yb, _justify(c, list(pair[1]), target))


def _draw_footer(c: _Canvas, size, month_key: str, record: Tuple[int, int],
                 cfg: Config, wordmark: Optional[Image.Image]) -> None:
    lay, pal = cfg.layout, cfg.palette
    W, H = size
    cx = W / 2.0

    if cfg.show_month:
        c.text((cx, H * lay.month_y), calendar.month_name[int(month_key[5:])].upper(),
               c.font(H * lay.month_size), pal.text,
               tracking=H * lay.month_size * lay.month_tracking, anchor="mc")

    if wordmark is not None:
        c.paste_centered(wordmark, (cx, H * lay.wordmark_y), W * lay.wordmark_width)

    c.text((cx, H * lay.record_y), "%d-%d" % record, c.font(H * lay.record_size),
           pal.text, tracking=H * lay.record_size * lay.record_tracking, anchor="mc")


def _resolve_month(cfg: Config) -> str:
    if cfg.month:
        return cfg.month
    tz = ZoneInfo(cfg.timezone) if ZoneInfo else timezone.utc
    return datetime.now(tz).strftime("%Y-%m")


def _wordmark(cfg: Config, season: int) -> Optional[Image.Image]:
    """White 'LOS ANGELES LAKERS' lettering, ball removed."""
    if cfg.wordmark_path:
        return assets.local_image(cfg.wordmark_path)
    urls = logo_urls(cfg.team, season)
    for rel, keyed in (("primary_logo_on_white_color", True),
                       ("primary_logo_on_black_color", True),
                       ("primary_logo_white", False)):
        url = urls.get(rel)
        if not url:
            continue
        img = (assets.extract_wordmark(url, cfg.team_color)
               if keyed else assets.remote_image(url))
        if img is not None:
            return img
    return None


def build(cfg: Config, ttl: Optional[int] = None
          ) -> Tuple[Image.Image, str, List[Game], Tuple[int, int]]:
    """Render the wallpaper. Returns (image, month_key, games shown, record)."""
    W, H = cfg.dimensions
    lay = cfg.layout
    want = _resolve_month(cfg)

    anchor = datetime(int(want[:4]), int(want[5:]), 1, tzinfo=timezone.utc)
    season = season_for(anchor)
    kwargs = {} if ttl is None else {"ttl": ttl}
    games = load_games(team=cfg.team, seasons=[season], tzname=cfg.timezone, **kwargs)
    if not games:  # e.g. next season not published yet
        games = load_games(team=cfg.team, seasons=[season - 1, season + 1],
                           tzname=cfg.timezone, **kwargs)

    month_key = want
    shown = games_in_month(games, month_key)
    if not shown:  # offseason: roll forward to the next month that has basketball
        fallback = next_month_with_games(games, want)
        if fallback:
            month_key, shown = fallback, games_in_month(games, fallback)

    if cfg.pad_odd_months and len(shown) % 2 == 1:
        shown = shown + [shown[-1]]

    shown_season = shown[0].season if shown else season
    record = season_record(games, shown_season, cfg.record_includes_postseason)

    base = background.load_background((W, H), cfg.background, align=cfg.background_align)
    base = background.apply_scrim(base, cfg.scrim, lay.grid_top, lay.record_y)
    c = _Canvas((W, H))

    if shown:
        rows = int(math.ceil(len(shown) / 2.0))
        band_top, band_bottom = H * lay.grid_top, H * lay.grid_bottom
        band = band_bottom - band_top
        pitch = min(band / rows, H * lay.max_pitch)   # never stretch light months
        chip_h = min(pitch * lay.chip_height_ratio, H * lay.chip_max_height)
        start_y = band_top + (band - pitch * rows) / 2.0

        col_w = W * (1 - 2 * lay.side_margin - lay.column_gutter) / 2.0
        col_x = (W * lay.side_margin, W * lay.side_margin + col_w + W * lay.column_gutter)

        for i, g in enumerate(shown):
            row, col = divmod(i, 2)               # row-major: L, R, L, R ...
            x0 = col_x[col]
            y0 = start_y + row * pitch + (pitch - chip_h) / 2.0
            _draw_chip(c, (x0, y0, x0 + col_w, y0 + chip_h), g, cfg)

    _draw_footer(c, (W, H), month_key, record, cfg, _wordmark(cfg, shown_season))
    return c.flatten_onto(base), month_key, shown, record
