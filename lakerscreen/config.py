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
    gold: RGBA = (253, 185, 39, 255)          # #FDB927, official Lakers gold
    purple: RGBA = (85, 37, 131, 255)         # #552583, official Lakers purple
    chip_fill: RGBA = (8, 8, 10, 236)
    chip_border: RGBA = (255, 255, 255, 255)
    chip_shadow: RGBA = (255, 255, 255, 150)  # the offset "sticker stack" edge
    text: RGBA = (255, 255, 255, 255)
    text_dim: RGBA = (176, 176, 182, 255)
    badge_fill: RGBA = (255, 255, 255, 255)     # W/L badge: white square...
    badge_text: RGBA = (0, 0, 0, 255)           # ...with a black letter
    live: RGBA = (255, 72, 72, 255)


@dataclass
class Layout:
    """All values are fractions of image width (x) or height (y).

    Derived from the reference mockup so the design scales to any iPhone.
    """
    # Vertical band the two-column grid may occupy (below clock, above footer).
    # Every value below was measured off the reference lock screen at 1206x2622.
    grid_top: float = 0.2700
    grid_bottom: float = 0.8700
    # Horizontal geometry.
    side_margin: float = 0.1450         # fraction of width
    column_gutter: float = 0.0550       # fraction of width
    # Chip proportions.
    max_pitch: float = 0.0744           # row-to-row spacing cap, of image height
    single_col_width: float = 0.4000    # chip width in single-column mode, of image width
    chip_height_ratio: float = 0.8300    # of the per-row pitch
    chip_max_height: float = 0.0680     # of image height, caps chips in light months
    corner_radius_ratio: float = 0.3200   # of chip height
    border_ratio: float = 0.0300         # of chip height
    stack_dx: float = -0.025            # sticker-stack offset, of chip height
    stack_dy: float = 0.069
    # Chip interior. Contents sit in two zones, each centred on itself.
    pad_x_ratio: float = 0.0850          # of chip width
    split: float = 0.6400
    split_compact: float = 0.7300       # split when the marker needs less room
    stripe_w: float = 0.075             # home/away edge stripe, of chip width
    # "pill" marker: a gold/purple capsule on the right holding the team code
    # stacked vertically, freeing the rest of the chip for date and time.
    pill_w: float = 0.125               # of chip width
    pill_h: float = 0.860               # of chip height
    pill_gap: float = 0.060             # space between text block and pill, of chip width
    pill_letter: float = 0.760          # letter size, of pill width
    pill_leading: float = 0.860         # line spacing, of letter size
    pill_text_mode: str = "auto"        # auto | dark | light; auto = dark on gold,
                                        # white on purple, for best contrast either way
    pill_text_boost: float = 1.45       # date/time enlargement in pill mode
    # "tag" marker: team code in a rounded rectangle built to the same corner
    # proportions as the W/L badge, so the two read as one shape language.
    tag_h: float = 0.3200                # tag height, of chip height
    tag_pad: float = 0.1600              # horizontal padding inside, of tag height
    tag_letter: float = 0.4800           # letter size, of tag height
    tag_tracking: float = 0.060
    tag_radius: float = 0.500          # tag corner radius, of tag height
    tag_shape: str = "circle"          # circle | pill
    tag_circle: float = 0.460          # circle diameter, of chip height
    tag_fit: float = 0.700             # share of the diameter the code may span
    tag_gap: float = 0.0450             # space between text block and tag, of chip width
    tag_right_pad: float = 0.0650       # tag inset from the chip's right edge
    justify_lines: bool = True         # stretch both lines to a shared width
    ref_line: str = "MON, 3/23"         # width every line is set to
    tag_outline: float = 0.000          # white keyline around the tag, of tag height
    tag_text_stroke: float = 0.032      # black keyline on the letters, of letter size
    tag_fill_accent: bool = True        # gold/purple tag + white letters,
                                        # else white tag + dark letters                # boundary between date zone and team zone
    zone_gap: float = 0.0550             # dead space at the boundary, of chip width
    line1_y: float = 0.355              # vertical centres of the two text lines
    line2_y: float = 0.645
    date_size: float = 0.3350           # font sizes, of chip height
    time_size: float = 0.2900
    vs_size: float = 0.2650
    team_size: float = 0.2900
    dot_w: float = 0.085                # home/away swatch, of chip height
    dot_h: float = 0.058
    dot_gap: float = 0.170              # space between vs/at and the swatch
    date_tracking: float = 0.0000
    date_gap: float = 0.4000           # space between weekday and date, of font size        # letter-spacing, as a fraction of font size
    vs_tracking: float = 0.250
    team_tracking: float = 0.2600
    badge_size: float = 0.1350           # W/L badge square, of chip height
    badge_radius: float = 0.500         # corner radius, of badge size
    badge_font: float = 0.620           # letter size inside the badge, of badge size
    result_gap: float = 0.2600            # space between the W/L badge and the score
    chip_vpad: float = 0.0850            # inner top/bottom margin, of chip height
    line_min_gap: float = 0.0700         # minimum ink gap between the two lines
    min_shrink: float = 0.62            # floor for auto-shrinking an overlong line
    # Footer.
    grid_bottom_pad: float = 0.0
    wordmark_y: float = 0.9094          # level with the flashlight/camera buttons
    wordmark_width: float = 0.235       # of image width
    record_y: float = 0.9345
    month_y: float = 0.8330
    month_size: float = 0.0215          # of image height
    record_size: float = 0.0112
    month_tracking: float = 0.300
    record_tracking: float = 0.150


@dataclass
class Config:
    device: str = DEFAULT_DEVICE
    size: Optional[Tuple[int, int]] = None
    timezone: str = "America/Los_Angeles"
    marker: str = "tag"                  # vs | tint | dot | stripe | pill | tag
    team: str = "lal"
    team_color: str = "552583"       # hex used to key the wordmark out of the logo
    wordmark_path: Optional[str] = None  # override with your own PNG
    background: Optional[str] = None
    background_align: str = "center"   # top | center | bottom crop for tall screens
    show_scores: bool = True
    record_includes_postseason: bool = False
    pad_odd_months: bool = True         # repeat the last game so rows stay paired
    single_column_max: int = 8          # <= this many games render in one centred column
    scrim: float = 0.15                 # darkening behind the grid, 0..1
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
