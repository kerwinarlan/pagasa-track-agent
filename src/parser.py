"""Deterministic parser for PAGASA bulletin text (stdlib only).

Parses the bulletin formats observed in real PAGASA Severe Weather Bulletins
2020-2024 (see data/raw/corpus):

* 2020-2021 era: "SEVERE WEATHER BULLETIN #1", FOR:/ISSUED AT headers,
  a Location of eye/center table, and "24 Hour (Tomorrow morning):
  <ref> (15.8N, 127.7E)" forecast bullets.
* 2022+ era: "TROPICAL CYCLONE BULLETIN NO./NR. N", a Location of Center
  section, a TRACK AND INTENSITY FORECAST table, and a TCWS table.

The parser is pure and deterministic: identical input always yields
identical output. It returns a ParseResult with a confidence score and
warnings; the caller decides whether to accept it or fall back to an LLM.

Timestamps are Philippine Standard Time (UTC+8) in the bulletin and are
canonicalized to UTC by the schema helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from src.schemas.bulletin import (
    Coordinate,
    ForecastPoint,
    StormBulletin,
    TyphoonCategory,
    WindSignalArea,
    WindSignalNumber,
    utc,
)

CORE_FIELDS = (
    "bulletin_number",
    "issued_at",
    "storm_name",
    "current_position",
    "max_sustained_winds_kmh",
)

# 16-point compass in degrees clockwise from true north.
# Long aliases ('Northwest') come from movement prose, short ones from tables.
_COMPASS_DEG: dict[str, float] = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5,
    "E": 90.0, "ESE": 112.5, "SE": 135.0, "SSE": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}

# Full-word compass names to their 16-point abbreviations. Movement prose
# uses full words ('Northwestward'); tables and the movement regex use
# abbreviations. compass_from_text canonicalizes to abbreviations.
_FULL_TO_ABBR: dict[str, str] = {
    "North": "N", "Northnortheast": "NNE", "Northeast": "NE", "Eastnortheast": "ENE",
    "East": "E", "Eastsoutheast": "ESE", "Southeast": "SE", "Southsoutheast": "SSE",
    "South": "S", "Southsouthwest": "SSW", "Southwest": "SW", "Westsouthwest": "WSW",
    "West": "W", "Westnorthwest": "WNW", "Northwest": "NW", "Northnorthwest": "NNW",
}

_BASE_DIRS: list[str] = [
    "northwest", "northeast", "southwest", "southeast",
    "north", "east", "south", "west",
]

# Two base tokens combine into a 16-point name, e.g. west + northwest = WNW.
_PAIR_TO_COMPASS: dict[tuple[str, str], str] = {
    ("north", "east"): "NE", ("east", "north"): "NE",
    ("north", "northeast"): "NNE", ("northeast", "north"): "NNE",
    ("northeast", "east"): "ENE", ("east", "northeast"): "ENE",
    ("east", "southeast"): "ESE", ("southeast", "east"): "ESE",
    ("southeast", "south"): "SSE", ("south", "southeast"): "SSE",
    ("south", "east"): "SE", ("east", "south"): "SE",
    ("south", "southwest"): "SSW", ("southwest", "south"): "SSW",
    ("southwest", "west"): "WSW", ("west", "southwest"): "WSW",
    ("south", "west"): "SW", ("west", "south"): "SW",
    ("north", "west"): "NW", ("west", "north"): "NW",
    ("north", "northwest"): "NNW", ("northwest", "north"): "NNW",
    ("northwest", "west"): "WNW", ("west", "northwest"): "WNW",
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

_RE_TITLE = re.compile(
    r"(?:SEVERE WEATHER BULLETIN|TROPICAL CYCLONE BULLETIN)\s*"
    r"(?:NO\.|NR\.|#)?\s*(\d+)\s*((-?\s*FINAL|-?F(?!\w))?)",
    re.IGNORECASE,
)
_RE_NAME_2020 = re.compile(
    r'FOR:\s*(?:[A-Z][A-Z ]+?)?["“]?([A-Z][A-Z ]+?)["”]?\s*(?:\(([A-Z]+)\))?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_RE_NAME_TITLE = re.compile(
    r'^(?:Super Typhoon|Typhoon|Severe Tropical Storm|Tropical Storm|'
    r'Tropical Depression)\s+["“”]?\s*([A-Z][A-Z ]+?)\s*["“”]?'
    r'\s*(?:\(([A-Z]+)\))?\s*$',
    re.IGNORECASE | re.MULTILINE,
)
_RE_ISSUED = re.compile(
    r"(?:ISSUED AT|Issued at)\s+(\d{1,2}):(\d{2})\s*(AM|PM|NN|MN)?"
    r"[,.]?\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
)
_RE_COORD = re.compile(
    r"\(?(\d{1,3}(?:\.\d+)?)\s*°?\s*([NS])\s*[,.]?\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])\)?"
)
_RE_MSW = re.compile(r"Maximum sustained winds? of (\d{1,3}) km/h", re.IGNORECASE)
_RE_GUSTS = re.compile(r"gustiness of up to (\d{1,3}) km/h", re.IGNORECASE)
_RE_PRESSURE = re.compile(r"central pressure of (\d{3})\s*hPa", re.IGNORECASE)
_RE_LOCATION_SECTION = re.compile(
    r"Location of\s*(?:eye/)?\s*center.*?(?=FORECAST\s+POSITIONS|TRACK\s+AND\s+INTENSITY"
    r"\s+FORECAST|TRACK\s+AND\s+INTENSITY\s+OUTLOOK|HAZARDS AFFECTING)",
    re.IGNORECASE | re.DOTALL,
)
_RE_ESTIMATED_AT = re.compile(
    r"estimated based on all available data\s+at\s+(.*?)\s*\(\s*\d+\.?\d*\s*°?\s*[NS]",
    re.IGNORECASE | re.DOTALL,
)
_RE_FORECAST_BULLET = re.compile(
    r"^[-\u2022\s]*(\d{2,3})\s*Hour\b[^\n:]*:\s*(.*)$", re.IGNORECASE | re.MULTILINE
)
_RE_FORECAST_TABLE = re.compile(
    r"^(\d{2,3})-Hour Forecast\b", re.IGNORECASE | re.MULTILINE
)
_RE_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*(AM|PM|NN|MN)?", re.IGNORECASE)
_RE_DATE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_RE_CATEGORY = re.compile(r"\b(\d{1,3})\s+(TD|TS|STS|TY|STY)\b")
_RE_SECTION_END = re.compile(
    r"TRACK\s+AND\s+INTENSITY\s+OUTLOOK|OTHER HAZARDS AFFECTING LAND AREAS|"
    r"HAZARDS AFFECTING COASTAL WATERS|TROPICAL\s+CYCLONE\s+WIND\s+SIGNALS?",
    re.IGNORECASE,
)
_RE_TCWS_HEADER = re.compile(
    r"TROPICAL CYCLONE WIND SIGNALS?\s*(?:\(TCWS\))?\s*IN EFFECT", re.IGNORECASE
)
_RE_NO_SIGNAL = re.compile(
    r"NO TROPICAL CYCLONE WIND SIGNAL IN EFFECT|No tropical cyclone wind signal"
    r" is (?:currently )?(?:hoisted|in effect)|Signal #\d is now lifted",
    re.IGNORECASE,
)
_RE_BARE_SIGNAL = re.compile(r"^\s*([1-5])\s*$", re.MULTILINE)
_RE_STATIONARY = re.compile(
    r"almost stationary|stationary|slowly|nearly stationary", re.IGNORECASE
)


@dataclass
class ParseResult:
    """Outcome of a deterministic parse."""

    bulletin: StormBulletin | None
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    fields_found: set[str] = field(default_factory=set)

    @property
    def accepted(self) -> bool:
        """True when the parse is complete enough to trust."""
        return self.bulletin is not None and self.confidence >= 0.8


def _parse_pht_time(hour: int, minute: int, meridiem: str | None) -> datetime:
    """Return a naive PHT datetime for the bulletin date, given later."""
    if meridiem is None:
        return datetime(2000, 1, 1, hour, minute)
    if meridiem.upper() == "NN":
        hour = 12
    elif meridiem.upper() == "MN":
        hour = 0
    elif meridiem.upper() == "PM" and hour != 12:
        hour += 12
    elif meridiem.upper() == "AM" and hour == 12:
        hour = 0
    return datetime(2000, 1, 1, hour, minute)


def _parse_date(day: int, month_name: str, year: int) -> datetime:
    month = _MONTHS[month_name.strip().lower()]
    return datetime(year, month, day)


def compass_from_text(phrase: str) -> tuple[str | None, str]:
    """Map a movement phrase to (16-point compass, raw phrase).

    'Slowly'/'almost stationary' nulls the speed, never the direction:
    'North northwestward slowly' is NNW with unknown speed. Direction
    words are matched exactly after stripping the 'ward' suffix, so
    'northwestward' is NW, not NNW.
    """
    phrase = re.sub(r"\s+", " ", phrase.strip(" .:;\u201d\u201c")).strip()
    if not phrase:
        return None, phrase
    clean = phrase.lower().replace("ward", "").replace("moving", "")
    tokens = re.findall(r"[a-z]+", clean)
    if len(tokens) >= 2:
        compass = _PAIR_TO_COMPASS.get((tokens[0], tokens[1]))
        if compass:
            return compass, phrase
    if tokens and tokens[0] in _BASE_DIRS:
        return _FULL_TO_ABBR[tokens[0].capitalize()], phrase
    if tokens:
        full = tokens[0].capitalize()
        if full in _FULL_TO_ABBR:
            return _FULL_TO_ABBR[full], phrase
    return None, phrase


def _movement_from_location_section(section: str) -> tuple[float | None, float | None, str | None]:
    """Extract (direction_deg, speed_kmh, raw_text) from the Location section.

    Skips header matches ('Movement dir. and speed') by requiring a valid
    compass phrase.
    """
    for match in re.finditer(
        r"(?:Present Movement|Moving|Movement)\s*:?\s*\n?\s*"
        r"([A-Za-z][A-Za-z\s]*?)(?:\s+at\s+(\d{1,3})\s*km/h)?(?=\s*$|\s*[.\n])",
        section,
        re.IGNORECASE,
    ):
        phrase = match.group(1)
        compass, phrase = compass_from_text(phrase)
        if compass is None:
            continue
        speed_text = match.group(2)
        speed: float | None = float(speed_text) if speed_text else None
        if _RE_STATIONARY.search(phrase):
            speed = None
        return _COMPASS_DEG.get(compass), speed, phrase
    return None, None, None


def _normalize(text: str) -> str:
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    text = text.replace("\u00a0", " ")
    text = text.replace("\u2022", "-").replace("\uf0b7", "-")
    return text


_RE_ROW_DIR = re.compile(
    r"\b(NNE|NNW|ENE|WNW|ESE|WSW|SSE|SSW|NE|NW|SE|SW|N|E|S|W)\b"
)

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _forecast_time(
    issued_at: datetime, label: str, numeric_hours: int
) -> datetime:
    """Forecast valid time for a 2020-era bullet, from its label.

    The label names the target day (for example 'Tomorrow morning',
    'Saturday afternoon'); some bulletins mislabel the hour count (two
    '96 Hour' bullets), so the weekday wins over the numeric prefix.
    Labels without a weekday ('Tonight') fall back to the numeric hours.
    """
    # The label names a PHT wall-clock time ('Saturday morning'), so apply
    # the day count and time of day in PHT, then return UTC.
    pht = issued_at.astimezone(timezone(timedelta(hours=8)))
    label_lower = label.lower()
    hours = None
    for name, weekday in _WEEKDAYS.items():
        if name in label_lower:
            weekday_hours = ((weekday - pht.weekday()) % 7) * 24
            # The numeric prefix is authoritative except when the label
            # points one day further out (PAGASA mislabels such bullets,
            # e.g. a real 120h forecast typed as '96 Hour').
            if weekday_hours > numeric_hours:
                hours = weekday_hours
            break
    if hours is None and "tomorrow" in label_lower:
        hours = 24
    if hours is None:
        hours = numeric_hours
    target = pht + timedelta(hours=hours)
    if "morning" in label_lower:
        target = target.replace(hour=5, minute=0, second=0)
    elif "noon" in label_lower:
        target = target.replace(hour=12, minute=0, second=0)
    elif "afternoon" in label_lower or "evening" in label_lower:
        target = target.replace(hour=17, minute=0, second=0)
    return target.astimezone(timezone.utc)


def _parse_forecast_bullets(
    text: str, issued_at: datetime, warnings: list[str]
) -> list[ForecastPoint]:
    """Parse the 2020-era forecast bullets: '24 Hour (label): <ref> (<coord>)'."""
    points: list[ForecastPoint] = []
    for match in _RE_FORECAST_BULLET.finditer(text):
        body = match.group(2)
        # The label parenthetical sits before the colon on the bullet line.
        label = ""
        label_match = re.search(r"\(([^)]*)\)", match.group(0))
        if label_match and not re.search(r"\d", label_match.group(1)):
            label = label_match.group(1)
        # Coordinates can wrap to the following line in PDF text extraction.
        extended = text[match.end():match.end() + 300]
        extended = re.split(r"^[-\u2022\s]*\d{2,3}\s*Hour\b", extended, 1, re.IGNORECASE | re.MULTILINE)[0]
        coord = _RE_COORD.search(body + "\n" + extended)
        if not coord:
            warnings.append("Forecast bullet without a coordinate.")
            continue
        lat, lon = float(coord.group(1)) * (1 if coord.group(2) == "N" else -1), \
                   float(coord.group(3)) * (1 if coord.group(4) == "E" else -1)
        points.append(
            ForecastPoint(
                timestamp=_forecast_time(issued_at, label, int(match.group(1))),
                position=Coordinate(lat=lat, lon=lon),
            )
        )
    return points


def _row_movement(rest: str) -> tuple[float | None, float | None]:
    """Extract (direction_deg, speed_kmh) from forecast-table row text.

    The row tail looks like 'NNE Slowly', 'NNW 20', or 'N 15'.
    """
    match = _RE_ROW_DIR.search(rest)
    if not match:
        return None, None
    direction = _COMPASS_DEG.get(match.group(1))
    after = rest[match.end():]
    speed: float | None = None
    if not _RE_STATIONARY.search(after):
        speed_match = re.search(r"(?:at\s*)?(\d{1,3})(?:\s*km/h)?", after)
        if speed_match:
            speed = float(speed_match.group(1))
    return direction, speed



def _parse_forecast_table(
    text: str, warnings: list[str]
) -> list[ForecastPoint]:
    """Parse the 2022+ TRACK AND INTENSITY FORECAST table rows."""
    points: list[ForecastPoint] = []
    anchors = list(_RE_FORECAST_TABLE.finditer(text))
    for index, anchor in enumerate(anchors):
        block_end = anchors[index + 1].start() if index + 1 < len(anchors) else len(text)
        block = text[anchor.end():block_end]
        end_marker = _RE_SECTION_END.search(block)
        if end_marker:
            block = block[:end_marker.start()]

        time_match = _RE_TIME.search(block)
        date_match = _RE_DATE.search(block)
        if not (time_match and date_match):
            warnings.append(f"Forecast row '{anchor.group(0)}' missing time or date.")
            continue
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        meridiem = time_match.group(3)
        day, month_name, year = (
            int(date_match.group(1)), date_match.group(2), int(date_match.group(3))
        )
        base = _parse_pht_time(hour, minute, meridiem)
        naive = base.replace(year=year, month=_MONTHS[month_name.strip().lower()], day=day)

        lat_lon: tuple[float, float] | None = None
        candidates = [float(m.group(0)) for m in re.finditer(r"\d{1,3}(?:\.\d+)?", block)]
        for first, second in zip(candidates, candidates[1:]):
            if 0.0 <= first <= 50.0 and 100.0 <= second <= 170.0:
                lat_lon = (first, second)
                break
        if lat_lon is None:
            warnings.append(f"Forecast row '{anchor.group(0)}' missing lat/lon.")
            continue

        category_match = _RE_CATEGORY.search(block)
        forecast_winds: float | None = None
        category: TyphoonCategory | None = None
        if category_match:
            forecast_winds = float(category_match.group(1))
            category = TyphoonCategory.from_label(category_match.group(2))

        direction, speed = _row_movement(block[category_match.end():] if category_match else block)

        points.append(
            ForecastPoint(
                timestamp=utc(naive),
                position=Coordinate(lat=lat_lon[0], lon=lat_lon[1]),
                max_sustained_winds_kmh=forecast_winds,
                category=category,
                movement_direction_deg=direction,
                movement_speed_kmh=speed,
            )
        )
    return points


def _parse_tcws(text: str) -> tuple[list[WindSignalArea], int | None, list[str]]:
    """Parse the TCWS section into per-signal areas plus the max signal."""
    warnings: list[str] = []
    if _RE_NO_SIGNAL.search(text):
        return [], None, warnings

    header = _RE_TCWS_HEADER.search(text)
    if not header:
        # Fall back to inline mentions, for example 'TCWS #1 and 2'.
        numbers: list[int] = []
        for m in re.finditer(r"TCWS\s*#?\s*(\d)(?:\s*(?:and|,|&|-)\s*(\d))?", text):
            numbers.append(int(m.group(1)))
            if m.group(2):
                numbers.append(int(m.group(2)))
        numbers += [int(n) for n in re.findall(r"Wind Signal No\.?\s*(\d)", text)]
        numbers = sorted(set(numbers))
        if numbers:
            return (
                [WindSignalArea(signal_number=WindSignalNumber(n)) for n in numbers],
                max(numbers),
                warnings,
            )
        return [], None, warnings

    section_end = _RE_SECTION_END.search(text, header.end())
    section = text[header.end():section_end.start() if section_end else len(text)]

    rows: list[tuple[int, list[str]]] = []
    current: tuple[int, list[str]] | None = None
    for line in section.splitlines():
        bare = _RE_BARE_SIGNAL.match(line)
        if bare:
            number = int(bare.group(1))
            if current is not None:
                rows.append(current)
            current = (number, [])
        elif current is not None and line.strip():
            current[1].append(line.strip())
    if current is not None:
        rows.append(current)

    noise = re.compile(
        r"^Wind threat:|^Warning lead time:|^Range of wind speeds:|"
        r"^Potential impacts of winds:|^Strong winds$|^Minimal to minor"
        r"|^Moderate|^High to very high|^\(Beaufort", re.IGNORECASE
    )
    areas: list[WindSignalArea] = []
    for number, lines in rows:
        # Split the row into region columns at dash-only separators.
        text_rows = " | ".join(l for l in lines if not noise.match(l) and l.strip("- ").strip())
        columns = [c.strip() for c in text_rows.split("|") if c.strip("- ").strip()]
        columns = [c for c in columns if not re.fullmatch(r"[- ]+", c) and c]
        if not columns:
            warnings.append(f"TCWS row #{number} yielded no areas.")
        areas.append(WindSignalArea(signal_number=WindSignalNumber(number), areas=columns))
    max_signal = max((a.signal_number.value for a in areas), default=None)
    return areas, max_signal, warnings


def deterministic_parse(raw_text: str) -> ParseResult:
    """Parse a raw bulletin deterministically; never raises on format issues."""
    text = _normalize(raw_text)
    warnings: list[str] = []
    fields: set[str] = set()

    # --- Header ---------------------------------------------------------
    title = _RE_TITLE.search(text)
    bulletin_number: int | None = None
    is_final = False
    if title:
        bulletin_number = int(title.group(1))
        is_final = bool(title.group(2))
        fields.add("bulletin_number")
    else:
        warnings.append("Bulletin title not recognized.")

    storm_name: str | None = None
    international_name: str | None = None
    name_match = _RE_NAME_TITLE.search(text) or _RE_NAME_2020.search(text)
    if name_match:
        storm_name = name_match.group(1).strip().strip('"').title()
        if name_match.lastindex and name_match.lastindex >= 2 and name_match.group(2):
            international_name = name_match.group(2)
        if storm_name:
            fields.add("storm_name")
    if not storm_name:
        warnings.append("Storm name not recognized.")

    issued_at: datetime | None = None
    issued = _RE_ISSUED.search(text)
    if issued:
        hour, minute = int(issued.group(1)), int(issued.group(2))
        meridiem = issued.group(3)
        day, month_name, year = int(issued.group(4)), issued.group(5), int(issued.group(6))
        if month_name.strip().lower() not in _MONTHS:
            warnings.append(f"Unknown month {month_name!r} in issue time.")
        else:
            naive = _parse_pht_time(hour, minute, meridiem)
            naive = naive.replace(
                year=year, month=_MONTHS[month_name.strip().lower()], day=day
            )
            issued_at = utc(naive)
            fields.add("issued_at")
    else:
        warnings.append("Issue time not recognized.")

    # --- Location / intensity / movement --------------------------------
    location_section = _RE_LOCATION_SECTION.search(text)
    section = location_section.group(0) if location_section else text

    coord = _RE_COORD.search(section)
    current_position: Coordinate | None = None
    position_description: str | None = None
    if coord:
        lat, lon = float(coord.group(1)) * (1 if coord.group(2) == "N" else -1), \
                   float(coord.group(3)) * (1 if coord.group(4) == "E" else -1)
        current_position = Coordinate(lat=lat, lon=lon)
        fields.add("current_position")
        desc_match = _RE_ESTIMATED_AT.search(section)
        if desc_match:
            position_description = re.sub(r"\(OUTSIDE PAR\)", "", desc_match.group(1), flags=re.IGNORECASE).strip()
        if current_position.outside_par:
            warnings.append("Current center is outside the PAR (informational).")
    else:
        warnings.append("Current position not found.")

    msw_match = _RE_MSW.search(text)
    max_winds: float | None = float(msw_match.group(1)) if msw_match else None
    if max_winds is not None:
        fields.add("max_sustained_winds_kmh")
    else:
        warnings.append("Maximum sustained winds not found.")

    gust_match = _RE_GUSTS.search(text)
    gustiness: float | None = float(gust_match.group(1)) if gust_match else None
    pressure_match = _RE_PRESSURE.search(text)
    pressure: float | None = float(pressure_match.group(1)) if pressure_match else None

    direction, speed, movement_text = _movement_from_location_section(section)

    # --- Forecast track ---------------------------------------------------
    forecast_points: list[ForecastPoint] = []
    if issued_at is not None:
        forecast_points = _parse_forecast_bullets(text, issued_at, warnings)
    if not forecast_points:
        forecast_points = _parse_forecast_table(text, warnings)
    if forecast_points:
        fields.add("forecast_track")

    # --- TCWS --------------------------------------------------------------
    signal_areas, signal_number, tcws_warnings = _parse_tcws(text)
    warnings.extend(tcws_warnings)

    # --- Assemble ------------------------------------------------------------
    confidence = len(fields & set(CORE_FIELDS)) / len(CORE_FIELDS)
    bulletin: StormBulletin | None = None
    if (
        bulletin_number is not None
        and issued_at is not None
        and storm_name is not None
        and current_position is not None
        and max_winds is not None
    ):
        category = TyphoonCategory.from_winds(max_winds)
        # Prefer the bulletin's own label when it matches the winds.
        label_match = _RE_CATEGORY.search(section)
        if label_match:
            label = TyphoonCategory.from_label(label_match.group(2))
            if label is not None and label == category:
                category = label
            elif label is not None:
                warnings.append(
                    f"Bulletin labels {label.value} but {max_winds} km/h implies "
                    f"{category.value}; using the wind-derived category."
                )
        try:
            bulletin = StormBulletin(
                bulletin_number=bulletin_number,
                issued_at=issued_at,
                storm_name=storm_name,
                international_name=international_name,
                is_final=is_final,
                typhoon_category=category,
                current_position=current_position,
                position_description=position_description,
                signal_number=WindSignalNumber(signal_number) if signal_number else None,
                wind_signal_areas=signal_areas,
                movement_speed_kmh=speed,
                movement_direction_deg=direction,
                movement_direction_text=movement_text,
                central_pressure_hpa=pressure,
                max_sustained_winds_kmh=max_winds,
                gustiness_kmh=gustiness,
                forecast_track=forecast_points,
            )
            bulletin_warnings = bulletin.warnings()
            if bulletin_warnings:
                warnings.extend(bulletin_warnings)
        except ValidationError as exc:
            warnings.append(f"Schema rejected the parse: {exc.errors()[0].get('msg', exc)}")
            bulletin = None
    return ParseResult(
        bulletin=bulletin,
        confidence=confidence,
        warnings=warnings,
        fields_found=fields,
    )
