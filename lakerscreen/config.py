"""Device presets, palette, and the layout/theme knobs for the wallpaper."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Native portrait pixel dimensions. Render at native res so iOS never rescales.
DEVICES: Dict[str, Tuple[int, int]] = {
    # iPhone 17 family reuses the 16 Pro panel sizes. If a screenshot from your
    # phone reports different dimensions, trust the screenshot and pass
    # --size WxH (or correct the entry here).
    "iphone-17-pro-max": (1320, 2868),
    "iphone-17-pro": (1206, 2622),
    "iphone-17": (1206, 2622),
    "iphone-16-pro-max": (1320, 2868),
    "iphone-16-pro": (1206, 2622),
    "iphone-16-plus": (1290, 2796),
    "iphone-16": (1179, 2556),
    "iphone-15-pro-max": (1290, 2796),
    "iphone-15-pro": (1179, 2556),
    "iphone-15": (1179, 2556),
    "iphone-14-pro-max": (1290, 2796),
    "iphone-14-pro": (1179, 2556),
    "iphone-14-plus": (1284, 2778),
    "iphone-14": (1170, 2532),
    "iphone-13": (1170, 2532),
    "iphone-13-mini": (1080, 2340),
    "iphone-se": (750, 1334),
}

DEFAULT_DEVICE = "iphone-17-pro"

RGBA = Tuple[int, int, int, int]


@dataclass
class Palette:
    gold: RGBA = (253, 185, 39, 255)          # home / "vs"
    purple: RGBA = (142, 94, 219, 255)        # away / "at" (brightened for dark bg)
    chip_fill: RGBA = (8, 8, 10, 236)
    chip_border: RGBA = (255, 255, 255, 255)
    chip_shadow: RGBA = (255, 255, 255, 150)  # the offset "sticker stack" edge
    text: RGBA = (255, 255, 255, 255)
    text_dim: RGBA = (176, 176, 182, 255)
    win: RGBA = (253, 185, 39, 255)
    loss: RGBA = (150, 150, 158, 255)
    live: RGBA = (255, 72, 72, 255)


@dataclass
class Layout:
    """All values are fractions of image width (x) or height (y).

    Derived from the reference mockup so the design scales to any iPhone.
    """
    # Vertical band the two-column grid may occupy (below clock, above footer).
    grid_top: float = 0.270
    grid_bottom: float = 0.856
    # Horizontal geometry.
    side_margin: float = 0.125          # fraction of width
    column_gutter: float = 0.051        # fraction of width
    # Chip proportions.
    chip_height_ratio: float = 0.68     # of the per-row pitch
    chip_max_height: float = 0.052      # of image height, caps chips in light months
    corner_radius_ratio: float = 0.30   # of chip height
    border_ratio: float = 0.048         # of chip height
    stack_dx: float = -0.018            # sticker-stack offset, of chip height
    stack_dy: float = 0.090
    # Chip interior. Contents are laid out in two zones, each centred on itself.
    pad_x_ratio: float = 0.060          # of chip width
    split: float = 0.635                # boundary between date zone and team zone
    zone_gap: float = 0.030             # dead space at the boundary, of chip width
    line1_y: float = 0.315              # vertical centres of the two text lines
    line2_y: float = 0.700
    date_size: float = 0.265            # font sizes, of chip height
    time_size: float = 0.315
    vs_size: float = 0.225
    team_size: float = 0.290
    dot_size: float = 0.105             # square swatch, of chip height
    date_tracking: float = 0.050        # letter-spacing, as a fraction of font size
    team_tracking: float = 0.170
    min_shrink: float = 0.62            # floor for auto-shrinking an overlong line
    # Footer.
    grid_bottom_pad: float = 0.0
    wordmark_y: float = 0.8970          # centre of the LAKERS wordmark
    wordmark_width: float = 0.235       # of image width
    record_y: float = 0.9345
    month_y: float = 0.8330
    month_size: float = 0.0215          # of image height
    record_size: float = 0.0138
    month_tracking: float = 0.300
    record_tracking: float = 0.150


@dataclass
class Config:
    device: str = DEFAULT_DEVICE
    size: Optional[Tuple[int, int]] = None
    timezone: str = "America/Los_Angeles"
    team: str = "lal"
    team_color: str = "552583"       # hex used to key the wordmark out of the logo
    wordmark_path: Optional[str] = None  # override with your own PNG
    background: Optional[str] = None
    background_align: str = "center"   # top | center | bottom crop for tall screens
    show_scores: bool = True
    record_includes_postseason: bool = False
    scrim: float = 0.34                 # darkening behind the grid, 0..1
    month: Optional[str] = None         # "YYYY-MM" override; default = today
    show_month: bool = False            # print the month name above the wordmark
    palette: Palette = field(default_factory=Palette)
    layout: Layout = field(default_factory=Layout)

    @property
    def dimensions(self) -> Tuple[int, int]:
        if self.size:
            return self.size
        if self.device not in DEVICES:
            raise SystemExit(
                "Unknown device %r. Choose one of: %s"
                % (self.device, ", ".join(sorted(DEVICES)))
            )
        return DEVICES[self.device]
