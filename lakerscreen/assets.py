"""Font resolution, letter-spaced text drawing, and team-logo caching."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional, Sequence, Tuple

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "assets", "cache")

# (path, ttc face index). First one that loads wins. The reference design uses a
# heavy condensed grotesque; these are the closest faces shipped with macOS.
FONT_CANDIDATES: Sequence[Tuple[str, int]] = (
    ("/System/Library/Fonts/Avenir Next Condensed.ttc", 8),   # Heavy
    ("/System/Library/Fonts/Avenir Next Condensed.ttc", 0),   # Bold
    ("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf", 0),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 9),           # Condensed Black
    ("/System/Library/Fonts/HelveticaNeue.ttc", 4),           # Condensed Bold
    ("/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf", 0),
    # Linux fallbacks, for rendering in CI.
    ("/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
)

_font_override: Optional[Tuple[str, int]] = None
_font_variation: Optional[str] = None


def set_font(path: str, index: int = 0, variation: Optional[str] = None) -> None:
    """Point the renderer at a specific font file (e.g. a downloaded Oswald).

    `variation` names an instance inside a variable font, e.g. "Bold".
    """
    global _font_override, _font_variation
    _font_override = (path, index)
    _font_variation = variation
    load_font.cache_clear()


@lru_cache(maxsize=256)
def load_font(size: int) -> ImageFont.FreeTypeFont:
    size = max(1, int(size))
    candidates: List[Tuple[str, int]] = list(FONT_CANDIDATES)
    if _font_override:
        candidates.insert(0, _font_override)
    for path, index in candidates:
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size, index=index)
        except Exception:
            continue
        if _font_variation and _font_override and path == _font_override[0]:
            try:
                font.set_variation_by_name(_font_variation)
            except Exception:
                pass
        return font
    return ImageFont.load_default()


def char_advance(font: ImageFont.FreeTypeFont, ch: str) -> float:
    return font.getlength(ch)


def tracked_width(font: ImageFont.FreeTypeFont, text: str, tracking_px: float) -> float:
    """Width of `text` when each glyph is followed by `tracking_px` of air."""
    if not text:
        return 0.0
    total = sum(char_advance(font, c) for c in text)
    return total + tracking_px * (len(text) - 1)


def draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill,
    tracking_px: float = 0.0,
    anchor: str = "lm",
) -> float:
    """Draw letter-spaced text. `anchor` accepts l/m/r for x and t/m/b/s for y.

    Pillow has no letter-spacing, so glyphs are placed individually.
    Returns the total advance width.
    """
    width = tracked_width(font, text, tracking_px)
    x, y = xy
    halign, valign = anchor[0], anchor[1]
    if halign == "m":
        x -= width / 2.0
    elif halign == "r":
        x -= width

    if valign == "c":
        # Centre on the actual ink, not the font box. All-caps strings have no
        # descenders, so the font-box centre renders visibly low.
        bbox = font.getbbox(text)
        y -= (bbox[1] + bbox[3]) / 2.0
        valign = "a"

    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill, anchor="l" + valign)
        x += char_advance(font, ch) + tracking_px
    return width


def team_logo(team: str = "lal", size: int = 128, dark: bool = True) -> Optional[Image.Image]:
    """ESPN's team roundel, cached on disk, resized to `size` px square."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    variant = "500-dark" if dark else "500"
    path = os.path.join(CACHE_DIR, "%s-%s.png" % (team, variant))
    if not os.path.exists(path):
        url = "https://a.espncdn.com/i/teamlogos/nba/%s/%s.png" % (variant, team)
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "curl/8.7.1"})
            resp.raise_for_status()
            with open(path, "wb") as fh:
                fh.write(resp.content)
        except Exception:
            return None
    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        return None
    return img.resize((size, size), Image.LANCZOS)


def _slugify(url: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in url)[-96:]


def remote_image(url: str, trim: bool = True) -> Optional[Image.Image]:
    """Download (and disk-cache) an image, optionally cropped to its ink bounds.

    ESPN's brand artwork is 4096x4096 with a lot of transparent padding, so the
    trim is what makes it possible to size the logo by its visible width.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, _slugify(url))
    if not path.endswith(".png"):
        path += ".png"
    if not os.path.exists(path):
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": "curl/8.7.1"})
            resp.raise_for_status()
            with open(path, "wb") as fh:
                fh.write(resp.content)
        except Exception:
            return None
    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        return None
    if trim:
        bbox = img.getchannel("A").getbbox()
        if bbox:
            img = img.crop(bbox)
    return img


def fit_width(img: Image.Image, width: float) -> Image.Image:
    """Scale an image to an exact pixel width, preserving aspect ratio."""
    w = max(1, int(round(width)))
    h = max(1, int(round(img.height * (w / float(img.width)))))
    return img.resize((w, h), Image.LANCZOS)


def _dominant_colors(img: Image.Image, top: int = 4, stride: int = 8):
    """Most common opaque colours. Subsampled - brand art is flat vector fills,
    so every 8th pixel finds the same palette for 1/64th the sort cost."""
    arr = np.asarray(img.convert("RGBA"))[::stride, ::stride]
    vis = arr[..., 3] > 128
    if not vis.any():
        return []
    cols, counts = np.unique(arr[..., :3][vis].reshape(-1, 3), axis=0, return_counts=True)
    return [tuple(int(v) for v in cols[i]) for i in np.argsort(-counts)[:top]]


def extract_wordmark(
    url: str,
    key_hex: str = "552583",
    tint=(255, 255, 255),
) -> Optional[Image.Image]:
    """Pull just the lettering out of a team's full-colour primary logo.

    ESPN publishes no standalone wordmark. The primary logo, though, is a
    two-colour lockup - lettering in the team colour over a ball in the
    secondary colour - so keying on the team colour isolates the wordmark. The
    mask is hard-edged at the source's 4096px; downscaling to render size
    supplies the antialiasing.
    """
    cache = os.path.join(
        CACHE_DIR,
        "wordmark_%s_%s_%02x%02x%02x.png" % ((_slugify(url)[-48:], key_hex) + tuple(tint)),
    )
    if os.path.exists(cache):
        try:
            return Image.open(cache).convert("RGBA")
        except Exception:
            pass

    src = remote_image(url, trim=False)
    if src is None:
        return None

    # int32 throughout: squared channel deltas reach ~65k and overflow int16.
    key = np.array([int(key_hex[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.int32)
    palette = _dominant_colors(src, top=4)
    if not palette:
        return None
    # The ESPN brand file rarely uses the exact published hex, so snap to
    # whichever dominant colour is nearest it.
    keyed = min(palette, key=lambda c: int(((np.array(c, dtype=np.int32) - key) ** 2).sum()))
    others = [c for c in palette if c != keyed]
    if not others:
        return None

    arr = np.asarray(src).astype(np.int32)
    rgb, alpha = arr[..., :3], arr[..., 3]
    d_key = ((rgb - np.array(keyed, dtype=np.int32)) ** 2).sum(-1)
    d_other = np.full(d_key.shape, np.iinfo(np.int32).max, dtype=np.int64)
    for c in others:
        d_other = np.minimum(d_other, ((rgb - np.array(c, dtype=np.int32)) ** 2).sum(-1))

    mask = (d_key < d_other) & (alpha > 128)
    if mask.sum() < 1000:
        return None

    out = np.zeros(arr.shape, dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = tint
    out[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
    img = Image.fromarray(out, mode="RGBA")
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    try:
        img.save(cache)
    except Exception:
        pass
    return img


def local_image(path: str, trim: bool = True) -> Optional[Image.Image]:
    """Load a wordmark/logo from disk, trimmed to its ink bounds."""
    try:
        img = Image.open(path).convert("RGBA")
    except Exception as exc:
        raise SystemExit("Could not open image %r: %s" % (path, exc))
    if trim:
        bbox = img.getchannel("A").getbbox()
        if bbox:
            img = img.crop(bbox)
    return img
