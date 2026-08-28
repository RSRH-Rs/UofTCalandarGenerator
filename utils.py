import re
from dataclasses import dataclass
from itertools import product
from urllib.parse import unquote

BASE_URL = "https://acorn.utoronto.ca/sws/rest"
COURSE_RE = re.compile(r"\b[A-Z]{3,4}\d{2,3}[A-Z]\d(?:\s+[FYS])?\b")
SECTION_RE = re.compile(r"\b(LEC|TUT|PRA|LAB|SEM)\s*(\d{1,4})\b")
ACTIVITY_TYPES = {
    "LECTURE": "LEC",
    "TUTORIAL": "TUT",
    "PRACTICAL": "PRA",
    "LABORATORY": "LAB",
    "SEMINAR": "SEM",
}
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


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


class AcornClient:
    def __init__(self, cookies: dict, token: str):
        import requests

        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.session.headers.update(
            {"Accept": "application/json", "X-XSRF-TOKEN": unquote(token)}
        )

    def _json(self, method: str, path: str, **kwargs):
        response = self.session.request(
            method, f"{BASE_URL}/{path}", timeout=20, **kwargs
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as error:
            raise RuntimeError("ACORN returned an invalid session response") from error

    def fetch_courses(self) -> list:
        registrations = self._json("GET", "enrolment/current-registrations")
        if not isinstance(registrations, list):
            raise RuntimeError("ACORN returned an unexpected registration response")

        sessions = []

        for registration in registrations:
            if not isinstance(registration, dict):
                continue
            session_code = registration.get("sessionCode")
            post = registration.get("post") or {}
            post_code = post.get("code")
            if not session_code or not post_code:
                continue

            payload = {"code": session_code, "posts": [{"code": post_code}]}
            timetable = self._json("POST", "timetable/viewTimetable", json=payload)
            label = (
                registration.get("sessionDescription")
                or registration.get("sessionName")
                or session_code
            )
            sessions.append({"label": str(label), "data": [registration, timetable]})

        return sessions


def extract_sections(data) -> dict[tuple[str, str], list[Section]]:
    """Extract course section choices from ACORN's nested responses."""
    groups: dict[tuple[str, str], dict[str, Section]] = {}

    def walk(value, course=""):
        if isinstance(value, list):
            for item in value:
                walk(item, course)
            return
        if not isinstance(value, dict):
            return

        current_course = _course_code(value) or course
        section_code = _section_code(value)
        meetings = _meetings(value) if section_code and current_course else []

        if meetings:
            activity = section_code.split()[0]
            section = Section(
                current_course,
                activity,
                section_code,
                tuple(sorted(set(meetings), key=_meeting_key)),
            )
            groups.setdefault((current_course, activity), {})[section_code] = section
            return

        for child in value.values():
            walk(child, current_course)

    walk(data)
    return {key: list(sections.values()) for key, sections in groups.items()}


def generate_timetables(
    groups: dict[tuple[str, str], list[Section]],
    days_off: set[int] | None = None,
    earliest: int | None = None,
    limit: int = 20,
) -> list[list[Section]]:
    days_off = days_off or set()
    choices = []

    for sections in groups.values():
        allowed = [
            section
            for section in sections
            if all(
                meeting.day not in days_off
                and (earliest is None or meeting.start >= earliest)
                for meeting in section.meetings
            )
        ]
        if not allowed:
            return []
        choices.append(allowed)

    schedules = []
    for combination in product(*choices):
        meetings = [meeting for section in combination for meeting in section.meetings]
        if _has_conflict(meetings):
            continue
        schedules.append(list(combination))
        if len(schedules) >= max(limit * 50, 500):
            break

    schedules.sort(key=_schedule_score)
    return schedules[:limit]


def split_periods(groups: dict[tuple[str, str], list[Section]]):
    terms = {course.rsplit(" ", 1)[-1] for course, _ in groups}
    periods = []
    for term in ("F", "S"):
        if term not in terms:
            continue
        selected = {
            key: sections
            for key, sections in groups.items()
            if key[0].rsplit(" ", 1)[-1] in {term, "Y"}
            or key[0].rsplit(" ", 1)[-1] not in {"F", "S", "Y"}
        }
        periods.append((f"{term}/Y courses", selected))
    return periods or [("All courses", groups)]


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
                f"  {_clock(meeting.start)}–{_clock(meeting.end)}  "
                f"{section.course} {section.code}{location}"
            )
    return "\n".join(lines)


def _course_code(value: dict) -> str:
    for key in ("courseCode", "course", "code", "name"):
        match = COURSE_RE.search(str(value.get(key, "")).upper())
        if match:
            return " ".join(match.group().split())
    return ""


def _section_code(value: dict) -> str:
    for key in (
        "sectionCode",
        "activityCode",
        "academicActivityCode",
        "activity",
        "code",
        "name",
    ):
        match = SECTION_RE.search(str(value.get(key, "")).upper())
        if match:
            return f"{match.group(1)} {match.group(2)}"

    activity = str(
        value.get("activityType")
        or value.get("activityTypeCode")
        or value.get("academicActivityCode")
        or value.get("teachingMethod")
        or value.get("type")
        or ""
    ).upper()
    activity = ACTIVITY_TYPES.get(activity, activity[:3])
    number = value.get("sectionNumber") or value.get("section")
    if activity in set(ACTIVITY_TYPES.values()) and number is not None:
        return f"{activity} {str(number).strip()}"
    return ""


def _meetings(value: dict) -> list[Meeting]:
    meetings = []

    def walk(item):
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if not isinstance(item, dict):
            return

        meeting = _meeting(item)
        if meeting:
            meetings.extend(meeting)
            return
        for child in item.values():
            walk(child)

    walk(value)
    return meetings


def _meeting(value: dict) -> list[Meeting]:
    lowered = {str(key).lower(): item for key, item in value.items()}
    day_value = next(
        (
            lowered[key]
            for key in (
                "meetingdayofweek",
                "dayofweek",
                "weekday",
                "meetingday",
                "day",
                "days",
            )
            if key in lowered
        ),
        None,
    )
    start = next(
        (
            lowered[key]
            for key in (
                "meetingstarttime",
                "starttime",
                "begintime",
                "start",
            )
            if key in lowered
        ),
        None,
    )
    end = next(
        (
            lowered[key]
            for key in (
                "meetingendtime",
                "endtime",
                "finishtime",
                "end",
            )
            if key in lowered
        ),
        None,
    )
    start_minutes, end_minutes = _time(start), _time(end)
    if day_value is None or start_minutes is None or end_minutes is None:
        return []

    location = next(
        (
            str(lowered[key]).strip()
            for key in ("location", "room", "building")
            if key in lowered and isinstance(lowered[key], (str, int))
        ),
        "",
    )
    days = (
        day_value if isinstance(day_value, list) else re.split(r"[,/]+", str(day_value))
    )
    return [
        Meeting(day, start_minutes, end_minutes, location)
        for raw_day in days
        if (day := _day(raw_day)) is not None
    ]


def _day(value) -> int | None:
    if isinstance(value, int) and 0 <= value <= 4:
        return value
    text = str(value).strip().upper()
    aliases = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4}
    if text[:2] in aliases:
        return aliases[text[:2]]
    for index, name in enumerate(DAY_NAMES):
        if text.startswith(name[:3].upper()):
            return index
    return None


def _time(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value < 24 * 60 else None
    text = str(value).strip().upper().replace(" ", "")
    match = re.search(r"(\d{1,2}):(\d{2})(AM|PM)?", text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    suffix = match.group(3)
    if suffix:
        hour = hour % 12 + (12 if suffix == "PM" else 0)
    return hour * 60 + minute


def _has_conflict(meetings: list[Meeting]) -> bool:
    for index, first in enumerate(meetings):
        for second in meetings[index + 1 :]:
            if (
                first.day == second.day
                and first.start < second.end
                and second.start < first.end
            ):
                return True
    return False


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


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
