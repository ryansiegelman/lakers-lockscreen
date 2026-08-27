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

    def font(self, size: float, weight: str = "heavy"):
        return assets.load_font(int(round(size * self.ss)), weight)

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
              fixed_gap: bool = False, weight: str = "heavy") -> Run:
    font = c.font(size, weight)
    return {"kind": "text", "text": text, "font": font, "fill": fill,
            "tracking": tracking, "gap": gap, "stroke": stroke,
            "stroke_fill": stroke_fill, "fixed_gap": fixed_gap,
            "w": c.text_width(text, font, tracking)}


def _badge_run(c: _Canvas, letter: str, size: float, radius: float, fill, text_fill,
               font_size: float, gap: float = 0.0, fixed_gap: bool = False) -> Run:
    """A filled rounded square with a letter knocked out of it."""
    return {"kind": "badge", "text": letter, "size": size, "radius": radius,
            "fill": fill, "text_fill": text_fill, "font": c.font(font_size),
            "gap": gap, "fixed_gap": fixed_gap, "w": size}


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


def _draw_runs(c: _Canvas, cx: float, cy: float, runs: Sequence[Run],
               align: str = "center") -> None:
    x = cx if align == "left" else cx - _runs_width(runs) / 2.0
    for i, r in enumerate(runs):
        if r["kind"] == "text":
            c.text((x, cy), r["text"], r["font"], r["fill"],
                   tracking=float(r["tracking"]), anchor="lc",
                   stroke_width=float(r.get("stroke", 0.0)),
                   stroke_fill=r.get("stroke_fill"))
        elif r["kind"] == "badge":
            sz = float(r["size"])
            c.rounded_rect((x, cy - sz / 2.0, x + sz, cy + sz / 2.0),
                           float(r["radius"]), fill=r["fill"])
            c.text((x + sz / 2.0, cy), str(r["text"]), r["font"], r["text_fill"],
                   anchor="mc")
        else:
            hh, ww = float(r["h"]), float(r["w"])
            c.rect((x, cy - hh / 2.0, x + ww, cy + hh / 2.0), fill=r["fill"])
        x += float(r["w"]) + (float(r["gap"]) if i < len(runs) - 1 else 0.0)


def _fmt_date(g: Game):
    """Weekday and date as separate runs, so the gap between them is tunable
    rather than being whatever a space character happens to measure."""
    return (g.start_local.strftime("%a").upper() + ",",
            g.start_local.strftime("%-m/%-d"))


def _fmt_time(g: Game) -> str:
    return g.start_local.strftime("%-I:%M %p").upper()


def _chip_lines(c: _Canvas, g: Game, cfg: Config, w: float, h: float, scale: float = 1.0):
    """The four lines of runs in a chip, built at a given type scale.

    Type is sized from chip height, but the zones it has to fit in are sized
    from chip width. When a month's chips are tall relative to their width the
    two disagree, so the scale is solved once per month (see _type_scale) and
    applied to every chip, keeping type identical across the grid.
    """
    lay, pal = cfg.layout, cfg.palette
    boost = lay.pill_text_boost if cfg.marker == "pill" else 1.0

    ds = h * lay.date_size * scale * boost
    weekday, datestr = _fmt_date(g)
    top_left = [_text_run(c, weekday, ds, pal.text, tracking=ds * lay.date_tracking,
                          gap=ds * lay.date_gap),
                _text_run(c, datestr, ds, pal.text, tracking=ds * lay.date_tracking)]

    s = h * lay.time_size * scale * boost
    if g.completed and g.won is not None:
        bs = h * lay.badge_size * scale
        bot_left = [_badge_run(c, "W" if g.won else "L", bs, bs * lay.badge_radius,
                               pal.badge_fill, pal.badge_text, bs * lay.badge_font,
                               gap=s * lay.result_gap, fixed_gap=True)]
        if cfg.show_scores and g.score_line:
            bot_left.append(_text_run(c, g.score_line, s, pal.text, weight="light"))
    elif g.state == "in":
        bot_left = [_text_run(c, "LIVE", s, pal.live, tracking=s * 0.06,
                              gap=s * lay.result_gap, fixed_gap=True)]
        if g.team_score is not None and g.opp_score is not None:
            bot_left.append(_text_run(c, "%d-%d" % (g.team_score, g.opp_score), s,
                                      pal.text_dim, weight="light"))
    else:
        bot_left = [_text_run(c, _fmt_time(g), s, pal.text, weight="light")]

    accent = pal.gold if g.is_home else pal.purple
    if cfg.marker in ("pill", "tag"):
        return top_left, bot_left, None, []
    ts = h * lay.team_size * scale
    team = lambda fill: [_text_run(c, g.opponent, ts, fill,
                                   tracking=ts * lay.team_tracking, weight="light")]

    if cfg.marker == "tint":
        # Colour carries home/away on its own; no word, no swatch.
        return top_left, bot_left, None, team(accent)
    if cfg.marker == "stripe":
        # Home/away moves to a stripe on the chip edge.
        return top_left, bot_left, None, team(pal.text)
    if cfg.marker == "dot":
        return (top_left, bot_left,
                [_swatch_run(h * lay.dot_w * scale, h * lay.dot_h * scale, accent)],
                team(pal.text))

    top_right = [_text_run(c, "vs" if g.is_home else "at", h * lay.vs_size * scale,
                           pal.text, tracking=h * lay.vs_size * scale * lay.vs_tracking,
                           gap=h * lay.dot_gap * scale),
                 _swatch_run(h * lay.dot_w * scale, h * lay.dot_h * scale, accent)]
    return top_left, bot_left, top_right, team(pal.text)


def _tag_metrics(c: _Canvas, cfg: Config, h: float, games: Sequence[Game]):
    """(width, height, letter size) for this month's team tags.

    Sized once for the month so every tag is identical and they form a column.
    A circle is a fixed diameter with the code scaled to fit inside it; a pill
    grows to whatever the widest code needs.
    """
    lay = cfg.layout
    if cfg.marker != "tag":
        return 0.0, 0.0, 0.0

    if lay.tag_shape == "circle":
        d = h * lay.tag_circle
        size = d * lay.tag_letter
        font = c.font(size)
        tr = size * lay.tag_tracking
        widest = max((c.text_width(g.opponent, font, tr) for g in games), default=0.0)
        room = d * lay.tag_fit
        if widest > room > 0:
            size *= room / widest          # shrink the code to sit inside the circle
        return d, d, size

    th = h * lay.tag_h
    size = th * lay.tag_letter
    font = c.font(size)
    tr = size * lay.tag_tracking
    widest = max((c.text_width(g.opponent, font, tr) for g in games), default=0.0)
    return widest + th * lay.tag_pad * 2.0, th, size


def _tag_width(c: _Canvas, cfg: Config, h: float, games: Sequence[Game]) -> float:
    return _tag_metrics(c, cfg, h, games)[0]


def _zones(cfg: Config, w: float, tag_w: float = 0.0):
    lay = cfg.layout
    pad = w * lay.pad_x_ratio
    half = w * lay.zone_gap / 2.0
    if cfg.marker == "tag":
        # Text block runs from the left padding to just short of the tag.
        right = w * lay.tag_right_pad
        return (pad, w - right - tag_w - w * lay.tag_gap, w - pad, w - pad)
    if cfg.marker == "pill":
        # One text block; the pill occupies the right edge and is drawn directly.
        pill = w * lay.pill_w + w * lay.pill_gap
        return (pad, w - pad - pill, w - pad, w - pad)
    split = lay.split if cfg.marker == "vs" else lay.split_compact
    lz0 = pad + (w * lay.stripe_w * 1.6 if cfg.marker == "stripe" else 0.0)
    lz1 = w * split - half
    rz0, rz1 = w * split + half, w - pad
    return (lz0, lz1, rz0, rz1)


def _vertical_scale(c: _Canvas, cfg: Config, h: float) -> float:
    """Largest type scale the chip's height allows before the two lines
    collide with each other or with the chip's top and bottom edges."""
    lay = cfg.layout
    cap = lambda f, txt: (f.getbbox(txt)[3] - f.getbbox(txt)[1]) / float(c.ss)
    cap_d = cap(c.font(h * lay.date_size), "SUN")
    cap_s = cap(c.font(h * lay.time_size, "light"), "128")
    if cap_d <= 0 or cap_s <= 0:
        return 1.0
    limits = [
        (lay.line1_y - lay.chip_vpad) * h / (cap_d / 2.0),
        ((1.0 - lay.chip_vpad) - lay.line2_y) * h / (cap_s / 2.0),
        ((lay.line2_y - lay.line1_y) - lay.line_min_gap) * h / (cap_d / 2.0 + cap_s / 2.0),
    ]
    return max(0.2, min(limits))


def _line_target(c: _Canvas, cfg: Config, w: float, h: float,
                 games: Sequence[Game], scale: float, tag_w: float) -> float:
    """Width every chip's text block is set to. Taken across the whole month so
    the blocks are identical and the tags line up, rather than each chip sizing
    itself to its own content."""
    lz0, lz1, _, _ = _zones(cfg, w, tag_w)
    widest = 0.0
    for g in games:
        tl, bl, _, _ = _chip_lines(c, g, cfg, w, h, scale)
        widest = max(widest, _runs_width(tl), _runs_width(bl))
    return min(widest, lz1 - lz0)


def _type_scale(c: _Canvas, cfg: Config, w: float, h: float, games: Sequence[Game],
                tag_w: float = 0.0) -> float:
    """Largest uniform type scale that fits both the zone widths and the chip
    height. Deliberately allowed above 1.0: without that the glyphs stay at
    their nominal size and any spare width is absorbed as letter-spacing
    instead, which reads as loose text rather than big text.
    """
    lz0, lz1, rz0, rz1 = _zones(cfg, w, tag_w)
    lw, rw = lz1 - lz0, rz1 - rz0
    scale = _vertical_scale(c, cfg, h)
    for g in games:
        tl, bl, tr, br = _chip_lines(c, g, cfg, w, h, 1.0)
        left = max(_runs_width(tl), _runs_width(bl))
        right = max(_runs_width(tr or []), _runs_width(br))
        if left > 0:
            scale = min(scale, lw / left)
        if right > 0:
            scale = min(scale, rw / right)
    return scale


def _draw_chip(c: _Canvas, box, g: Game, cfg: Config, scale: float = 1.0,
               tag_w: float = 0.0, line_target: float = 0.0,
               tag_h: float = 0.0, tag_letter: float = 0.0) -> None:
    lay, pal = cfg.layout, cfg.palette
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    radius = h * lay.corner_radius_ratio
    border = h * lay.border_ratio

    if lay.border_ratio > 0:
        dx, dy = h * lay.stack_dx, h * lay.stack_dy
        c.rounded_rect((x0 + dx, y0 + dy, x1 + dx, y1 + dy), radius,
                       fill=pal.chip_fill, outline=pal.chip_shadow, width=border)
        c.rounded_rect((x0, y0, x1, y1), radius,
                       fill=pal.chip_fill, outline=pal.chip_border, width=border)
    else:
        c.rounded_rect((x0, y0, x1, y1), radius, fill=pal.chip_fill)

    lz0, lz1, rz0, rz1 = _zones(cfg, w, tag_w)
    lcx, rcx = x0 + (lz0 + lz1) / 2.0, x0 + (rz0 + rz1) / 2.0
    lw, rw = lz1 - lz0, rz1 - rz0
    ya, yb = y0 + h * lay.line1_y, y0 + h * lay.line2_y

    tl, bl, tr, br = _chip_lines(c, g, cfg, w, h, scale)
    _tag_x1 = x1 - w * lay.tag_right_pad if cfg.marker == "tag" else None

    if cfg.marker == "tag":
        accent = pal.gold if g.is_home else pal.purple
        th = tag_h or h * lay.tag_h
        lsz = tag_letter or th * lay.tag_letter
        font = c.font(lsz)
        tr_px = lsz * lay.tag_tracking
        tw = tag_w if tag_w > 0 else c.text_width(g.opponent, font, tr_px) + th * lay.tag_pad * 2
        tx1 = _tag_x1 if _tag_x1 is not None else x1 - w * lay.tag_right_pad
        tcy = (y0 + y1) / 2.0
        c.rounded_rect((tx1 - tw, tcy - th / 2.0, tx1, tcy + th / 2.0),
                       th * (0.5 if lay.tag_shape == "circle" else lay.tag_radius),
                       fill=accent if lay.tag_fill_accent else pal.badge_fill,
                       outline=pal.chip_border if lay.tag_outline > 0 else None,
                       width=th * lay.tag_outline)
        c.text((tx1 - tw / 2.0, tcy), g.opponent, font,
               pal.text if lay.tag_fill_accent else pal.badge_text,
               tracking=tr_px, anchor="mc",
               stroke_width=th * lay.tag_letter * lay.tag_text_stroke,
               stroke_fill=pal.badge_text)

    if cfg.marker == "pill":
        pw = w * lay.pill_w
        ph = h * lay.pill_h
        px0 = x1 - w * lay.pad_x_ratio - pw
        py0 = y0 + (h - ph) / 2.0
        c.rounded_rect((px0, py0, px0 + pw, py0 + ph), pw / 2.0,
                       fill=pal.gold if g.is_home else pal.purple)
        letters = list(g.opponent)
        lsz = pw * lay.pill_letter
        lead = lsz * lay.pill_leading
        font = c.font(lsz)
        mode = lay.pill_text_mode
        if mode == "auto":
            # Gold is light enough to take dark letters; the purple is not.
            fill = pal.badge_text if g.is_home else pal.text
        else:
            fill = pal.badge_text if mode == "dark" else pal.text
        top = py0 + ph / 2.0 - lead * (len(letters) - 1) / 2.0
        for i, ch in enumerate(letters):
            c.text((px0 + pw / 2.0, top + i * lead), ch, font, fill, anchor="mc")

    if cfg.marker == "stripe":
        sw = w * lay.stripe_w
        inset = h * lay.border_ratio * 1.5
        c.rounded_rect((x0 + inset * 1.6, y0 + inset * 2.2,
                        x0 + inset * 1.6 + sw, y1 - inset * 2.2),
                       sw / 2.0, fill=pal.gold if g.is_home else pal.purple)

    if lay.justify_lines:
        # Both lines start at the chip's left padding and stretch across the
        # full zone to the tag, so every chip's text spans the same span and
        # the left edges form a column.
        target = lw
        _draw_runs(c, x0 + lz0, ya, _justify(c, list(tl), target), align="left")
        _draw_runs(c, x0 + lz0, yb, _justify(c, list(bl), target), align="left")
    else:
        # Both lines start at the same x and keep their natural spacing.
        # Stretching them to a common width made a short line like "2:00 PM"
        # crawl with letter-spacing, and stretched by a different amount
        # depending on whether the game had been played.
        _draw_runs(c, x0 + lz0, ya, list(tl), align="left")
        _draw_runs(c, x0 + lz0, yb, list(bl), align="left")

    if tr is None:
        _draw_runs(c, rcx, (ya + yb) / 2.0, list(br))
    elif lay.justify_lines:
        target = min(max(_runs_width(tr), _runs_width(br)), rw)
        _draw_runs(c, rcx, ya, _justify(c, list(tr), target))
        _draw_runs(c, rcx, yb, _justify(c, list(br), target))
    else:
        _draw_runs(c, rcx, ya, list(tr))
        _draw_runs(c, rcx, yb, list(br))


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

    c.text((cx, H * lay.record_y), "%d-%d" % record,
           c.font(H * lay.record_size, "light"), pal.text,
           tracking=H * lay.record_size * lay.record_tracking, anchor="mc")


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

    single = 0 < len(shown) <= cfg.single_column_max
    if cfg.pad_odd_months and not single and len(shown) % 2 == 1:
        # Fill the odd slot with the next game on the calendar rather than
        # repeating one. If the season ends here there is nothing to borrow,
        # so the grid stays odd instead of showing a game twice.
        later = [x for x in games if x.start_utc > shown[-1].start_utc]
        if later:
            shown = shown + [later[0]]

    shown_season = shown[0].season if shown else season
    record = season_record(games, shown_season, cfg.record_includes_postseason)

    base = background.load_background((W, H), cfg.background, align=cfg.background_align)
    base = background.apply_scrim(base, cfg.scrim, lay.grid_top, lay.record_y)
    c = _Canvas((W, H))

    if shown:
        cols = 1 if single else 2
        rows = int(math.ceil(len(shown) / float(cols)))
        band_top, band_bottom = H * lay.grid_top, H * lay.grid_bottom
        band = band_bottom - band_top
        pitch = min(band / rows, H * lay.max_pitch)   # never stretch light months
        chip_h = min(pitch * lay.chip_height_ratio, H * lay.chip_max_height)
        start_y = band_top + (band - pitch * rows) / 2.0

        if cols == 1:
            col_w = W * lay.single_col_width
            col_x = ((W - col_w) / 2.0,)
        else:
            col_w = W * (1 - 2 * lay.side_margin - lay.column_gutter) / 2.0
            col_x = (W * lay.side_margin, W * lay.side_margin + col_w + W * lay.column_gutter)

        tag_w, tag_h_px, tag_letter_px = _tag_metrics(c, cfg, chip_h, shown)
        scale = _type_scale(c, cfg, col_w, chip_h, shown, tag_w)
        line_target = _line_target(c, cfg, col_w, chip_h, shown, scale, tag_w)
        for i, g in enumerate(shown):
            row, col = divmod(i, cols)            # row-major: L, R, L, R ...
            x0 = col_x[col]
            y0 = start_y + row * pitch + (pitch - chip_h) / 2.0
            _draw_chip(c, (x0, y0, x0 + col_w, y0 + chip_h), g, cfg, scale,
                       tag_w, line_target, tag_h_px, tag_letter_px)

    _draw_footer(c, (W, H), month_key, record, cfg, _wordmark(cfg, shown_season))
    return c.flatten_onto(base), month_key, shown, record
