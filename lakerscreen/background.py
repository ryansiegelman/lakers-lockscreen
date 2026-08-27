"""Wallpaper backgrounds: cover-crop a supplied photo, or synthesise dark water."""
from __future__ import annotations

import os
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BG_DIR = os.path.join(ROOT, "assets", "backgrounds")


def cover_crop(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    """Scale + centre-crop so the image exactly fills `size` without distortion."""
    tw, th = size
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(tw, int(round(sw * scale))), max(th, int(round(sh * scale)))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def _sample_bilinear(tex: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Wrap-around bilinear sample of `tex` at float coords (u, v)."""
    h, w = tex.shape
    u0, v0 = np.floor(u).astype(np.int32), np.floor(v).astype(np.int32)
    fu, fv = u - u0, v - v0
    u0m, v0m = u0 % w, v0 % h
    u1m, v1m = (u0 + 1) % w, (v0 + 1) % h
    a = tex[v0m, u0m] * (1 - fu) + tex[v0m, u1m] * fu
    b = tex[v1m, u0m] * (1 - fu) + tex[v1m, u1m] * fu
    return a * (1 - fv) + b * fv


def _noise_tex(res: int, rng: np.random.Generator) -> np.ndarray:
    """Smooth tileable value noise, produced by upsampling a small random grid."""
    small = rng.random((res, res)).astype(np.float32)
    tiled = np.tile(small, (2, 2))
    img = Image.fromarray((tiled * 255).astype(np.uint8), mode="L")
    img = img.resize((512, 512), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32) / 255.0


def generate_water(size: Tuple[int, int], seed: int = 7) -> Image.Image:
    """A dark, rippled water surface seen in perspective.

    Pixel rows are mapped through a 1/y perspective warp so ripples compress
    toward the top of the frame, then lit with a narrow specular term to get the
    thin bright crests of the reference image.
    """
    w, h = size
    rng = np.random.default_rng(seed)

    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    yn, xn = ys / float(h), xs / float(w)

    # Perspective: distance grows toward the top of the frame. Clamped so the
    # far field does not alias into visible tiling.
    world_y = np.minimum(1.0 / (yn + 0.16), 5.4)
    world_x = (xn - 0.5) * world_y * 1.9
    # Domain warp breaks up the degenerate centre column (world_x == 0 for every
    # row), which otherwise reads as a seam straight down the middle.
    world_x = world_x + 0.28 * np.sin(world_y * 2.3) + 0.11 * np.cos(world_y * 5.7)

    height = np.zeros((h, w), dtype=np.float32)
    amp, freq = 1.0, 1.0
    for octave in range(5):
        tex = _noise_tex(8 + octave * 6, rng)
        ou, ov = rng.random() * 512.0, rng.random() * 512.0
        u = (world_x * freq * 26.0 + ou) % 512.0
        v = (world_y * freq * 26.0 + ov) % 512.0
        height += amp * _sample_bilinear(tex, u, v)
        amp *= 0.52
        freq *= 2.07
    height /= height.max()

    # Facet lighting: steep slopes along the view axis catch the light.
    gy, gx = np.gradient(height)
    slope = np.abs(gy * 2.6) + np.abs(gx * 0.7)
    slope /= (slope.max() + 1e-6)
    spec = np.clip(slope * 3.2, 0.0, 1.0) ** 2.1

    # Ripple banding gives the surface its corrugated read.
    band = 0.5 + 0.5 * np.sin(height * 34.0 + world_y * 0.7)
    spec = np.clip(spec * 0.72 + band * 0.28 * np.clip(1.25 - yn, 0, 1), 0, 1)

    # Flatten the far field so the horizon fades out instead of showing detail.
    horizon = np.clip(yn / 0.34, 0.0, 1.0) ** 0.8
    spec *= 0.18 + 0.82 * horizon

    base = 0.048 + 0.030 * horizon
    lum = base + spec * (0.30 * (0.35 + 0.65 * (1.0 - yn)))
    lum = np.clip(lum, 0.0, 1.0)

    rgb = np.stack([lum * 0.92, lum * 0.97, lum * 1.06], axis=-1)   # cool cast
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), mode="RGB")
    return img.filter(ImageFilter.GaussianBlur(0.6))


def _cached_water(size: Tuple[int, int], seed: int) -> Image.Image:
    cache = os.path.join(ROOT, "assets", "cache", "water-%dx%d-%d.png" % (size[0], size[1], seed))
    if os.path.exists(cache):
        try:
            return Image.open(cache).convert("RGB")
        except Exception:
            pass
    img = generate_water(size, seed=seed)
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    img.save(cache)
    return img


def load_background(size: Tuple[int, int], path: Optional[str] = None, seed: int = 7) -> Image.Image:
    """User-supplied image if given, else assets/backgrounds/default.*, else synthetic."""
    candidates = []
    if path:
        candidates.append(path)
    for ext in ("jpg", "jpeg", "png", "heic", "webp"):
        candidates.append(os.path.join(DEFAULT_BG_DIR, "default." + ext))

    for cand in candidates:
        if cand and os.path.exists(cand):
            try:
                return cover_crop(Image.open(cand).convert("RGB"), size)
            except Exception as exc:
                if path and cand == path:
                    raise SystemExit("Could not open background %r: %s" % (path, exc))
    return _cached_water(size, seed)


def apply_scrim(img: Image.Image, strength: float, top: float, bottom: float) -> Image.Image:
    """Darken a vertical band so chip text stays legible over a busy photo."""
    if strength <= 0:
        return img
    w, h = img.size
    yn = (np.arange(h, dtype=np.float32) / float(h))[:, None]
    # Smooth ramp in, flat through the grid, ramp out below the footer.
    fade = 0.10
    a = np.clip((yn - (top - fade)) / fade, 0, 1)
    b = np.clip(((bottom + fade) - yn) / fade, 0, 1)
    mask = np.clip(np.minimum(a, b), 0, 1) * strength
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr *= (1.0 - mask)[:, :, None]
    return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), mode="RGB")
