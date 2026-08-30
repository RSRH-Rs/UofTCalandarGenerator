"""Course data and timetable generation.

Sections come from the public U of T Timetable Builder (TTB) API, which lists
every offered section of a course rather than only the one a student enrolled
in. No ACORN sign-in and no personal data are involved.
"""

import json
import os
import re
import sys
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

TTB_BASE = "https://api.easi.utoronto.ca/ttb"
TTB_URL = f"{TTB_BASE}/getCoursesByCodeAndSectionCode"
SEARCH_URL = f"{TTB_BASE}/getOptimizedMatchingCourseTitles"
DIVISIONS_URL = f"{TTB_BASE}/getMatchingDivisions"
SESSIONS_URL = f"{TTB_BASE}/current-session"

COURSE_CODE_RE = re.compile(r"^[A-Z]{3}[A-Z0-9]\d{2}[A-Z]\d$")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
TERM_NAMES = {"9": "Fall", "1": "Winter", "5": "Summer"}
SUB_SESSION_NAMES = {"F": "First", "S": "Second"}

# Used only if the reference endpoints are unreachable, so that search still
# covers the common cases instead of failing outright.
FALLBACK_DIVISIONS = ("APSC", "ARTSC", "ERIN", "SCAR")

# TTB can return tens of thousands of section combinations for a handful of
# courses. Bound both the search itself and how many complete timetables are
# kept before scoring, so the UI stays responsive.
MAX_SEARCH_STEPS = 400_000
MAX_CANDIDATES = 2_000


class CourseNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Meeting:
    day: int
    start: int
    end: int
    location: str = ""


@dataclass(frozen=True)
class Section:
    course: str
    activity: str
    code: str
    meetings: tuple[Meeting, ...]
    asynchronous: bool = False


@dataclass(frozen=True)
class Offering:
    """One course as offered in one session, with all of its sections."""

    course: str
    title: str
    campus: str
    session: str
    sections: tuple[Section, ...]

    @property
    def code(self) -> str:
        return self.course.split()[0]

    @property
    def label(self) -> str:
        return f"{self.course} — {self.title}"


@dataclass(frozen=True)
class CourseMatch:
    """A search hit: enough to show a suggestion and then look the course up."""

    code: str
    term: str
    title: str
    division: str

    @property
    def label(self) -> str:
        return f"{self.code} {self.term} — {self.title}  ·  {self.division}"


def fetch_offerings(code: str, timeout: int = 20) -> list[Offering]:
    """Look up every offering of ``code`` (e.g. ``CSC108H1``) across sessions."""
    code = normalize_code(code)
    if not COURSE_CODE_RE.match(code):
        raise CourseNotFound(f"{code} is not a valid course code (e.g. CSC108H1)")

    import requests

    response = requests.get(
        f"{TTB_URL}/{code}", timeout=timeout, headers={"Accept": "application/json"}
    )
    if response.status_code == 404:
        raise CourseNotFound(f"{code} is not in the Timetable Builder catalogue")
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError("Timetable Builder returned an invalid response") from error

    offerings = parse_offerings(payload)
    if not offerings:
        raise CourseNotFound(f"{code} has no scheduled sections")
    return offerings


def fetch_many(codes, timeout: int = 20) -> tuple[list[Offering], list[str]]:
    """Look up several codes, reporting the ones that could not be loaded."""
    offerings, failed = [], []
    for code in codes:
        try:
            offerings.extend(fetch_offerings(code, timeout=timeout))
        except Exception:
            failed.append(normalize_code(code))
    return offerings, failed


def search_courses(term: str, limit: int = 40, timeout: int = 15) -> list[CourseMatch]:
    """Type-ahead search over course codes, titles and descriptions."""
    term = str(term).strip()
    if not term:
        return []

    import requests

    divisions, sessions = _reference_data(timeout)
    response = requests.get(
        SEARCH_URL,
        params={
            "term": term,
            "divisions": list(divisions),
            "sessions": list(sessions),
            # The endpoint rejects the request without both thresholds; they
            # bound how many ranked matches come back.
            "lowerThreshold": 50,
            "upperThreshold": 200,
        },
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()

    matches = (
        ((response.json() or {}).get("payload") or {}).get("codesAndTitles") or []
    )
    results = []
    for match in matches:
        if not isinstance(match, dict) or not match.get("code"):
            continue
        division = match.get("division") or {}
        results.append(
            CourseMatch(
                code=str(match["code"]).strip(),
                term=str(match.get("sectionCode") or "").strip(),
                title=str(match.get("name") or "").strip(),
                division=str(division.get("code") or "").strip(),
            )
        )
        if len(results) >= limit:
            break
    return results


_REFERENCE: dict = {}


def _reference_data(timeout: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Divisions and session codes that search must be scoped to.

    Both come from TTB itself so that a new academic session needs no code
    change; the result is cached for the life of the process.
    """
    import requests

    if _REFERENCE:
        return _REFERENCE["divisions"], _REFERENCE["sessions"]

    headers = {"Accept": "application/json"}
    try:
        payload = requests.get(DIVISIONS_URL, timeout=timeout, headers=headers).json()
        divisions = tuple(
            str(item["value"])
            for item in payload.get("payload") or []
            if item.get("value")
        )
    except Exception:
        divisions = ()

    try:
        payload = requests.get(SESSIONS_URL, timeout=timeout, headers=headers).json()
        sessions = tuple(
            str(item["value"])
            for item in payload.get("payload") or []
            # Header rows are group captions ("Fall-Winter 2026-2027"), not
            # session codes.
            if item.get("value") and not item.get("header")
        )
    except Exception:
        sessions = ()

    _REFERENCE["divisions"] = divisions or FALLBACK_DIVISIONS
    _REFERENCE["sessions"] = sessions
    return _REFERENCE["divisions"], _REFERENCE["sessions"]


def normalize_code(code: str) -> str:
    """TTB matches course codes exactly, so strip spaces and force upper case."""
    return "".join(str(code).split()).upper()


def parse_offerings(payload) -> list[Offering]:
    courses = (
        ((payload or {}).get("payload") or {}).get("pageableCourse") or {}
    ).get("courses") or []

    offerings = []
    for course in courses:
        if not isinstance(course, dict) or course.get("cancelInd") == "Y":
            continue
        code = str(course.get("code") or "").strip()
        term = str(course.get("sectionCode") or "").strip()
        if not code:
            continue
        name = f"{code} {term}".strip()

        sections = []
        for raw in course.get("sections") or []:
            section = _parse_section(raw, name)
            if section:
                sections.append(section)
        if not sections:
            continue

        for session in course.get("sessions") or [""]:
            offerings.append(
                Offering(
                    course=name,
                    title=str(course.get("name") or "").strip(),
                    campus=str(course.get("campus") or "").strip(),
                    session=str(session),
                    sections=tuple(sections),
                )
            )
    return offerings


def group_sections(
    offerings: list[Offering],
) -> dict[tuple[str, str], list[Section]]:
    """Collect sections into the choices the generator picks between.

    One group per (course, activity): pick exactly one LEC, one TUT, and so on.
    """
    groups: dict[tuple[str, str], dict[str, Section]] = {}
    for section in chain.from_iterable(o.sections for o in offerings):
        groups.setdefault((section.course, section.activity), {})[
            section.code
        ] = section
    return {key: list(value.values()) for key, value in sorted(groups.items())}


def apply_pins(
    groups: dict[tuple[str, str], list[Section]],
    pins: dict[tuple[str, str], str] | None,
) -> dict[tuple[str, str], list[Section]]:
    """Narrow a group to the one section the user pinned, where they pinned one.

    A pin naming a section that is no longer offered is ignored rather than
    left to empty the group, which would make every timetable impossible.
    """
    pins = pins or {}
    narrowed = {}
    for key, sections in groups.items():
        pinned = [s for s in sections if s.code == pins.get(key)]
        narrowed[key] = pinned or sections
    return narrowed


def section_summary(section: Section) -> str:
    if section.asynchronous:
        return "Asynchronous (Online)"
    return ", ".join(
        f"{DAY_NAMES[meeting.day][:3]} {clock(meeting.start)}–{clock(meeting.end)}"
        for meeting in section.meetings
    )


def config_path() -> Path:
    """Where the saved course list lives.

    A frozen one-file build unpacks into a temp directory that is wiped on
    exit, so ``__file__`` is useless there; use a per-user app data folder.
    """
    if getattr(sys, "frozen", False):
        base = Path(
            os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home()
        ) / "UofT-Timetable-Generator"
        base.mkdir(parents=True, exist_ok=True)
        return base / "courses.json"
    return Path(__file__).with_name(".ttb_courses.json")


def load_config() -> dict:
    try:
        config = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def save_config(config: dict) -> None:
    try:
        config_path().write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError:
        pass


def encode_pins(pins: dict[tuple[str, str], str]) -> dict[str, str]:
    """JSON has no tuple keys, so flatten ``(course, activity)`` to a string."""
    return {f"{course}|{activity}": code for (course, activity), code in pins.items()}


def decode_pins(stored) -> dict[tuple[str, str], str]:
    pins = {}
    for key, code in (stored or {}).items():
        course, _, activity = str(key).partition("|")
        if course and activity and isinstance(code, str):
            pins[(course, activity)] = code
    return pins


def session_label(session: str) -> str:
    """``20269`` -> ``Fall 2026``; ``20265F`` -> ``Summer 2026 (First)``."""
    match = re.fullmatch(r"(\d{4})(\d)([FS]?)", str(session))
    if not match:
        return str(session) or "Unknown session"
    year, term, sub = match.groups()
    label = f"{TERM_NAMES.get(term, 'Session')} {year}"
    return f"{label} ({SUB_SESSION_NAMES[sub]})" if sub else label


def allowed_sections(
    sections: list[Section],
    days_off: set[int] | None = None,
    earliest: int | None = None,
) -> list[Section]:
    days_off = days_off or set()
    return [
        section
        for section in sections
        if all(
            meeting.day not in days_off
            and (earliest is None or meeting.start >= earliest)
            for meeting in section.meetings
        )
    ]


def blocked_groups(
    groups: dict[tuple[str, str], list[Section]],
    days_off: set[int] | None = None,
    earliest: int | None = None,
) -> list[tuple[str, str]]:
    """Groups whose every section is ruled out by the preferences.

    A single one of these makes the whole search impossible, so naming them is
    far more useful than reporting that no timetable was found.
    """
    return [
        key
        for key, sections in groups.items()
        if not allowed_sections(sections, days_off, earliest)
    ]


def unavoidable_conflicts(
    groups: dict[tuple[str, str], list[Section]],
    days_off: set[int] | None = None,
    earliest: int | None = None,
) -> list[tuple[tuple[str, str], tuple[str, str]]]:
    """Pairs of groups for which every allowed section pairing overlaps.

    This does not replace the full timetable search: conflicts can involve
    three or more groups even when every pair has at least one compatible
    choice.  It is a useful explanation when a pair alone makes the requested
    timetable impossible, though.
    """
    allowed_groups = [
        (key, allowed_sections(sections, days_off, earliest))
        for key, sections in groups.items()
    ]
    conflicts = []
    for index, (left_key, left_sections) in enumerate(allowed_groups):
        if not left_sections:
            continue
        for right_key, right_sections in allowed_groups[index + 1 :]:
            if not right_sections:
                continue
            if all(
                any(
                    _overlaps(left_meeting, right_meeting)
                    for left_meeting in left.meetings
                    for right_meeting in right.meetings
                )
                for left in left_sections
                for right in right_sections
            ):
                conflicts.append((left_key, right_key))
    return conflicts


def generate_timetables(
    groups: dict[tuple[str, str], list[Section]],
    days_off: set[int] | None = None,
    earliest: int | None = None,
    limit: int = 20,
    minimum_days_off: int = 0,
) -> list[list[Section]]:
    """Return up to ``limit`` conflict-free timetables, best-scoring first."""
    minimum_days_off = max(0, min(5, minimum_days_off))
    maximum_used_days = 5 - minimum_days_off
    choices = []
    for sections in groups.values():
        allowed = allowed_sections(sections, days_off, earliest)
        if not allowed:
            return []
        choices.append(allowed)

    # Groups with the fewest options first: conflicts surface earlier, so whole
    # branches get pruned instead of being enumerated.
    choices.sort(key=len)

    schedules: list[list[Section]] = []
    steps = MAX_SEARCH_STEPS

    def walk(index: int, chosen: list[Section], meetings: list[Meeting]) -> None:
        nonlocal steps
        if index == len(choices):
            schedules.append(list(chosen))
            return
        for section in choices[index]:
            if steps <= 0 or len(schedules) >= MAX_CANDIDATES:
                return
            steps -= 1
            if any(
                _overlaps(meeting, placed)
                for meeting in section.meetings
                for placed in meetings
            ):
                continue
            used_days = {meeting.day for meeting in (*meetings, *section.meetings)}
            if len(used_days) > maximum_used_days:
                continue
            count = len(section.meetings)
            chosen.append(section)
            meetings.extend(section.meetings)
            walk(index + 1, chosen, meetings)
            chosen.pop()
            if count:
                del meetings[-count:]

    walk(0, [], [])
    schedules.sort(key=_schedule_score)
    return schedules[:limit]


def format_timetable(schedule: list[Section], number: int) -> str:
    lines = [f"Schedule {number}"]
    meetings = [
        (meeting, section) for section in schedule for meeting in section.meetings
    ]

    for day in range(5):
        daily = sorted(
            ((meeting, section) for meeting, section in meetings if meeting.day == day),
            key=lambda item: item[0].start,
        )
        if not daily:
            continue
        lines.append(DAY_NAMES[day])
        for meeting, section in daily:
            location = f" · {meeting.location}" if meeting.location else ""
            lines.append(
                f"  {clock(meeting.start)}–{clock(meeting.end)}  "
                f"{section.course} {section.code}{location}"
            )
    asynchronous = [section for section in schedule if section.asynchronous]
    if asynchronous:
        lines.append("Asynchronous (Online)")
        lines.extend(f"  {section.course} {section.code}" for section in asynchronous)
    return "\n".join(lines)


def clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _parse_section(raw, course: str) -> Section | None:
    if not isinstance(raw, dict) or raw.get("cancelInd") == "Y":
        return None
    activity = str(raw.get("teachMethod") or "").strip().upper()
    number = str(raw.get("sectionNumber") or "").strip()
    if not activity or not number:
        return None

    meetings = []
    for raw_meeting in raw.get("meetingTimes") or []:
        meeting = _parse_meeting(raw_meeting)
        if meeting:
            meetings.append(meeting)
    delivery_modes = {
        str(item.get("mode") or "").strip().upper()
        for item in raw.get("deliveryModes") or []
        if isinstance(item, dict)
    }
    asynchronous = "ASYNC" in delivery_modes
    if not meetings and not asynchronous:
        # A TBA section has no usable scheduling information. Unlike a known
        # asynchronous section, treating it as conflict-free would be unsafe.
        return None

    return Section(
        course=course,
        activity=activity,
        code=f"{activity} {number}",
        meetings=tuple(sorted(set(meetings), key=_meeting_key)),
        asynchronous=asynchronous,
    )


def _parse_meeting(raw) -> Meeting | None:
    if not isinstance(raw, dict):
        return None
    start, end = raw.get("start") or {}, raw.get("end") or {}
    day = _day(start.get("day"))
    start_minutes = _minutes(start.get("millisofday"))
    end_minutes = _minutes(end.get("millisofday"))
    if day is None or start_minutes is None or end_minutes is None:
        return None
    if end_minutes <= start_minutes:
        return None
    return Meeting(day, start_minutes, end_minutes, _location(raw.get("building")))


def _day(value) -> int | None:
    """TTB numbers days Monday=1 … Sunday=7; weekends have no grid column."""
    if not isinstance(value, int) or not 1 <= value <= 5:
        return None
    return value - 1


def _minutes(value) -> int | None:
    if not isinstance(value, int) or not 0 <= value < 24 * 60 * 60 * 1000:
        return None
    return value // 60_000


def _location(building) -> str:
    if not isinstance(building, dict):
        return ""
    code = _room_part(building.get("buildingCode"))
    room = _room_part(building.get("buildingRoomNumber"))
    suffix = _room_part(building.get("buildingRoomSuffix"))
    return " ".join(part for part in (code, room + suffix) if part)


def _room_part(value) -> str:
    """TTB uses runs of dashes as a placeholder for an unassigned room."""
    text = str(value or "").strip()
    return "" if set(text) <= {"-"} else text


def _overlaps(first: Meeting, second: Meeting) -> bool:
    return (
        first.day == second.day
        and first.start < second.end
        and second.start < first.end
    )


def _schedule_score(schedule: list[Section]):
    by_day = {day: [] for day in range(5)}
    for section in schedule:
        for meeting in section.meetings:
            by_day[meeting.day].append(meeting)

    used_days = sum(bool(items) for items in by_day.values())
    gaps = 0
    for items in by_day.values():
        ordered = sorted(items, key=lambda meeting: meeting.start)
        gaps += sum(
            max(0, right.start - left.end) for left, right in zip(ordered, ordered[1:])
        )
    return used_days, gaps


def _meeting_key(meeting: Meeting):
    return meeting.day, meeting.start, meeting.end, meeting.location
