"""Fetch and normalise the Lakers schedule from ESPN's public site API."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9
    ZoneInfo = None  # type: ignore

import requests

SCHEDULE_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/"
    "{team}/schedule?season={season}&seasontype={seasontype}"
)
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "cache")
CACHE_TTL = 900  # seconds; ESPN scores settle within minutes of a final

# ESPN 403s a fair number of user-agents (browser-like strings included). These
# are tried in order; the first that returns 200 wins.
USER_AGENTS = (
    "curl/8.7.1",
    "curl/7.88.1",
    "Wget/1.21.4",
    "python-requests/2.32",
)

REGULAR, POSTSEASON = 2, 3

# ESPN's abbreviations differ from the broadcast-style 3-letter codes used in the
# reference design. Normalise so every code is exactly three characters.
ABBREV_OVERRIDES: Dict[str, str] = {
    "GS": "GSW", "NO": "NOL", "NY": "NYK", "SA": "SAS", "UTAH": "UTA",
    "WSH": "WAS", "PHX": "PHO", "NOP": "NOL", "BKN": "BKN",
}


@dataclass
class Game:
    event_id: str
    start_utc: datetime
    start_local: datetime
    opponent: str
    is_home: bool
    state: str                 # "pre" | "in" | "post"
    completed: bool
    team_score: Optional[int]
    opp_score: Optional[int]
    won: Optional[bool]
    season: int
    season_type: int

    @property
    def month_key(self) -> str:
        return self.start_local.strftime("%Y-%m")

    @property
    def score_line(self) -> str:
        if self.team_score is None or self.opp_score is None:
            return ""
        hi, lo = max(self.team_score, self.opp_score), min(self.team_score, self.opp_score)
        return "%d-%d" % (hi, lo)


def season_for(dt: datetime) -> int:
    """NBA seasons are labelled by their ending year; they tip off in October."""
    return dt.year + 1 if dt.month >= 7 else dt.year


def _cache_path(team: str, season: int, seasontype: int) -> str:
    return os.path.join(CACHE_DIR, "%s-%d-%d.json" % (team, season, seasontype))


def _fetch_raw(team: str, season: int, seasontype: int, ttl: int = CACHE_TTL) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(team, season, seasontype)
    if ttl and os.path.exists(path) and (time.time() - os.path.getmtime(path)) < ttl:
        with open(path) as fh:
            return json.load(fh)

    url = SCHEDULE_URL.format(team=team, season=season, seasontype=seasontype)
    data = None
    last_error: Optional[Exception] = None
    for ua in USER_AGENTS:
        try:
            resp = requests.get(
                url, timeout=20,
                headers={"User-Agent": ua, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_error = exc
    if data is None:
        # Never let a flaky network wipe out a working wallpaper: fall back to
        # whatever we cached last, however stale.
        if os.path.exists(path):
            with open(path) as fh:
                return json.load(fh)
        raise RuntimeError("ESPN request failed for %s: %s" % (url, last_error))
    with open(path, "w") as fh:
        json.dump(data, fh)
    return data


def _parse_event(ev: dict, team_abbr: str, tz, season: int, seasontype: int) -> Optional[Game]:
    comps = ev.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]

    us = them = None
    for c in comp.get("competitors", []):
        if (c.get("team") or {}).get("abbreviation", "").upper() == team_abbr.upper():
            us = c
        else:
            them = c
    if us is None or them is None:
        return None

    start_utc = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    start_local = start_utc.astimezone(tz) if tz else start_utc

    status = (comp.get("status") or {}).get("type") or {}
    state = status.get("state", "pre")
    completed = bool(status.get("completed"))

    def _score(c: dict) -> Optional[int]:
        s = c.get("score")
        if isinstance(s, dict):
            s = s.get("value")
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return None

    ts, os_ = _score(us), _score(them)
    won: Optional[bool] = None
    if completed:
        if us.get("winner") is not None or them.get("winner") is not None:
            won = bool(us.get("winner"))
        elif ts is not None and os_ is not None:
            won = ts > os_

    raw = (them.get("team") or {}).get("abbreviation", "???").upper()
    return Game(
        event_id=str(ev.get("id")),
        start_utc=start_utc,
        start_local=start_local,
        opponent=ABBREV_OVERRIDES.get(raw, raw)[:3],
        is_home=us.get("homeAway") == "home",
        state=state,
        completed=completed,
        team_score=ts,
        opp_score=os_,
        won=won,
        season=season,
        season_type=seasontype,
    )


def load_games(
    team: str = "lal",
    seasons: Optional[Sequence[int]] = None,
    tzname: str = "America/Los_Angeles",
    ttl: int = CACHE_TTL,
) -> List[Game]:
    """Return every known game for the given seasons, sorted by tip-off."""
    tz = ZoneInfo(tzname) if ZoneInfo else timezone.utc
    if seasons is None:
        seasons = [season_for(datetime.now(timezone.utc))]

    games: Dict[str, Game] = {}
    for season in seasons:
        for seasontype in (REGULAR, POSTSEASON):
            try:
                data = _fetch_raw(team, season, seasontype, ttl=ttl)
            except Exception:
                continue
            abbr = (data.get("team") or {}).get("abbreviation", team)
            for ev in data.get("events") or []:
                g = _parse_event(ev, abbr, tz, season, seasontype)
                if g is not None:
                    games[g.event_id] = g
    return sorted(games.values(), key=lambda g: g.start_utc)


def games_in_month(games: Iterable[Game], month_key: str) -> List[Game]:
    return [g for g in games if g.month_key == month_key]


def next_month_with_games(games: Sequence[Game], from_key: str) -> Optional[str]:
    keys = sorted({g.month_key for g in games})
    for k in keys:
        if k >= from_key:
            return k
    return keys[-1] if keys else None


def season_record(
    games: Iterable[Game], season: int, include_postseason: bool = False
) -> Tuple[int, int]:
    """Won-lost for a season. Regular season only by default, which is what a
    team's quoted record means; playoff results are conventionally separate."""
    wins = losses = 0
    for g in games:
        if g.season != season or not g.completed or g.won is None:
            continue
        if not include_postseason and g.season_type != REGULAR:
            continue
        if g.won:
            wins += 1
        else:
            losses += 1
    return wins, losses


def logo_urls(team: str = "lal", season: Optional[int] = None, ttl: int = 86400) -> Dict[str, str]:
    """Map ESPN logo `rel` names (e.g. "primary_logo_white") to their URLs."""
    if season is None:
        season = season_for(datetime.now(timezone.utc))
    out: Dict[str, str] = {}
    for st in (REGULAR, POSTSEASON):
        try:
            data = _fetch_raw(team, season, st, ttl=ttl)
        except Exception:
            continue
        abbr = (data.get("team") or {}).get("abbreviation", team).upper()
        # The full brand set (wordmarks included) only appears on the per-event
        # competitor objects; the top-level `team.logos` is usually empty.
        for ev in data.get("events") or []:
            for comp in ev.get("competitions") or []:
                for c in comp.get("competitors") or []:
                    t = c.get("team") or {}
                    if t.get("abbreviation", "").upper() != abbr:
                        continue
                    for logo in t.get("logos") or []:
                        href = logo.get("href")
                        for rel in logo.get("rel") or []:
                            if href and rel not in out:
                                out[rel] = href
            if out:
                break
        if out:
            break
    return out
