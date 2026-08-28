import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import utils
from utils import (
    CourseNotFound,
    Meeting,
    Section,
    apply_pins,
    clock,
    decode_pins,
    encode_pins,
    fetch_offerings,
    format_timetable,
    generate_timetables,
    group_sections,
    load_config,
    normalize_code,
    parse_offerings,
    save_config,
    search_courses,
    section_summary,
    session_label,
)

# A trimmed capture of the live Timetable Builder response for CSC108H1 and
# MAT135H1, so the parser is tested against the real payload shape offline.
SAMPLE = json.loads(
    (Path(__file__).with_name("ttb_sample.json")).read_text(encoding="utf-8")
)


def _section(course, code, *meetings):
    activity = code.split()[0]
    return Section(course, activity, code, tuple(meetings))


class ParsingTests(unittest.TestCase):
    def test_parses_every_offering(self):
        offerings = parse_offerings(SAMPLE)
        keys = {(offering.course, offering.session) for offering in offerings}

        self.assertIn(("CSC108H1 F", "20269"), keys)
        self.assertIn(("MAT135H1 F", "20265F"), keys)
        # The same course code is offered separately in Summer and Fall; those
        # must stay distinct so their sections are never mixed together.
        self.assertIn(("MAT135H1 F", "20269"), keys)

    def test_meeting_times_and_location(self):
        offering = next(
            item
            for item in parse_offerings(SAMPLE)
            if (item.course, item.session) == ("CSC108H1 F", "20269")
        )
        section = next(s for s in offering.sections if s.code == "LEC 0201")

        self.assertEqual(section.activity, "LEC")
        self.assertEqual(len(section.meetings), 2)
        monday = section.meetings[0]
        self.assertEqual(monday.day, 0)  # TTB day 1 is Monday
        self.assertEqual(clock(monday.start), "13:00")
        self.assertEqual(monday.location, "PB B250")

    def test_groups_are_per_course_and_activity(self):
        fall = [o for o in parse_offerings(SAMPLE) if o.session == "20269"]
        groups = group_sections(fall)

        self.assertGreater(len(groups[("CSC108H1 F", "LEC")]), 1)
        self.assertIn(("MAT135H1 F", "TUT"), groups)
        self.assertNotIn(("CSC108H1 S", "LEC"), groups)

    def test_ignores_cancelled_and_unscheduled_sections(self):
        payload = {
            "payload": {
                "pageableCourse": {
                    "courses": [
                        {
                            "code": "CSC108H1",
                            "sectionCode": "F",
                            "sessions": ["20269"],
                            "sections": [
                                {
                                    "teachMethod": "LEC",
                                    "sectionNumber": "0101",
                                    "cancelInd": "Y",
                                    "meetingTimes": [
                                        {
                                            "start": {"day": 1, "millisofday": 0},
                                            "end": {"day": 1, "millisofday": 3600000},
                                        }
                                    ],
                                },
                                {
                                    "teachMethod": "LEC",
                                    "sectionNumber": "0201",
                                    "cancelInd": "N",
                                    "meetingTimes": [],
                                },
                                {
                                    "teachMethod": "LEC",
                                    "sectionNumber": "0301",
                                    "cancelInd": "N",
                                    "meetingTimes": [
                                        {
                                            "start": {
                                                "day": 5,
                                                "millisofday": 9 * 3600000,
                                            },
                                            "end": {
                                                "day": 5,
                                                "millisofday": 10 * 3600000,
                                            },
                                        }
                                    ],
                                },
                            ],
                        }
                    ]
                }
            }
        }
        sections = parse_offerings(payload)[0].sections
        self.assertEqual([section.code for section in sections], ["LEC 0301"])

    def test_session_labels(self):
        self.assertEqual(session_label("20269"), "Fall 2026")
        self.assertEqual(session_label("20271"), "Winter 2027")
        self.assertEqual(session_label("20265"), "Summer 2026")
        self.assertEqual(session_label("20265F"), "Summer 2026 (First)")
        self.assertEqual(session_label("weird"), "weird")

    def test_rejects_malformed_course_codes(self):
        self.assertEqual(normalize_code(" csc108h1 "), "CSC108H1")
        with self.assertRaises(CourseNotFound):
            fetch_offerings("CSC108")


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.groups = group_sections(
            [o for o in parse_offerings(SAMPLE) if o.session == "20269"]
        )

    def test_produces_multiple_distinct_timetables(self):
        schedules = generate_timetables(self.groups, limit=10)

        self.assertGreater(len(schedules), 1)
        codes = {
            tuple(sorted((s.course, s.code) for s in schedule))
            for schedule in schedules
        }
        self.assertEqual(len(codes), len(schedules))
        for schedule in schedules:
            self.assertEqual(len(schedule), len(self.groups))

    def test_respects_days_off_and_earliest(self):
        schedules = generate_timetables(self.groups, earliest=14 * 60, limit=10)
        for schedule in schedules:
            for section in schedule:
                for meeting in section.meetings:
                    self.assertGreaterEqual(meeting.start, 14 * 60)

        # Every MAT135H1 tutorial in the fixture is on a Friday.
        self.assertEqual(generate_timetables(self.groups, days_off={4}), [])

    def test_rejects_overlapping_sections(self):
        groups = {
            ("AAA100H1 F", "LEC"): [
                _section("AAA100H1 F", "LEC 0101", Meeting(0, 600, 660)),
            ],
            ("BBB100H1 F", "LEC"): [
                _section("BBB100H1 F", "LEC 0101", Meeting(0, 630, 690)),
                _section("BBB100H1 F", "LEC 0201", Meeting(0, 660, 720)),
            ],
        }
        schedules = generate_timetables(groups)

        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0][1].code, "LEC 0201")

    def test_prefers_fewer_days_then_smaller_gaps(self):
        groups = {
            ("AAA100H1 F", "LEC"): [
                _section("AAA100H1 F", "LEC 0101", Meeting(0, 600, 660)),
            ],
            ("BBB100H1 F", "LEC"): [
                _section("BBB100H1 F", "LEC 0101", Meeting(1, 600, 660)),
                _section("BBB100H1 F", "LEC 0201", Meeting(0, 780, 840)),
                _section("BBB100H1 F", "LEC 0301", Meeting(0, 660, 720)),
            ],
        }
        schedules = generate_timetables(groups)

        self.assertEqual(
            [schedule[1].code for schedule in schedules],
            ["LEC 0301", "LEC 0201", "LEC 0101"],
        )

    def test_format(self):
        schedule = generate_timetables(self.groups, limit=1)[0]
        output = format_timetable(schedule, 1)

        self.assertIn("Schedule 1", output)
        self.assertIn("CSC108H1 F", output)
        self.assertIn("Monday", output)


class PinTests(unittest.TestCase):
    def setUp(self):
        self.groups = group_sections(
            [o for o in parse_offerings(SAMPLE) if o.session == "20269"]
        )
        self.key = ("MAT135H1 F", "TUT")

    def test_pin_narrows_only_the_pinned_group(self):
        wanted = self.groups[self.key][1].code
        narrowed = apply_pins(self.groups, {self.key: wanted})

        self.assertEqual([s.code for s in narrowed[self.key]], [wanted])
        self.assertEqual(
            len(narrowed[("CSC108H1 F", "LEC")]),
            len(self.groups[("CSC108H1 F", "LEC")]),
        )

    def test_pin_is_honoured_by_the_generator(self):
        wanted = self.groups[self.key][1].code
        schedules = generate_timetables(
            apply_pins(self.groups, {self.key: wanted}), limit=10
        )

        self.assertTrue(schedules)
        for schedule in schedules:
            pinned = next(s for s in schedule if (s.course, s.activity) == self.key)
            self.assertEqual(pinned.code, wanted)

    def test_stale_pin_does_not_empty_the_group(self):
        narrowed = apply_pins(self.groups, {self.key: "TUT 9999"})
        self.assertEqual(len(narrowed[self.key]), len(self.groups[self.key]))

    def test_pins_survive_a_json_round_trip(self):
        pins = {("CSC108H1 F", "LEC"): "LEC 0201", ("MAT135H1 F", "TUT"): "TUT 0403"}
        self.assertEqual(decode_pins(json.loads(json.dumps(encode_pins(pins)))), pins)
        self.assertEqual(decode_pins({"nopipe": "LEC 0101"}), {})
        self.assertEqual(decode_pins(None), {})

    def test_section_summary(self):
        section = self.groups[("CSC108H1 F", "LEC")][0]
        self.assertRegex(section_summary(section), r"^[A-Z][a-z]{2} \d\d:\d\d–\d\d:\d\d")


class ConfigTests(unittest.TestCase):
    def test_round_trip_and_missing_file(self):
        original = utils.config_path
        with TemporaryDirectory() as directory:
            path = Path(directory) / "courses.json"
            utils.config_path = lambda: path
            try:
                self.assertEqual(load_config(), {})
                save_config({"courses": ["CSC108H1"], "session": "20269"})
                self.assertEqual(load_config()["courses"], ["CSC108H1"])

                path.write_text("not json", encoding="utf-8")
                self.assertEqual(load_config(), {})
            finally:
                utils.config_path = original


class SearchTests(unittest.TestCase):
    def test_blank_term_makes_no_request(self):
        self.assertEqual(search_courses("   "), [])


if __name__ == "__main__":
    unittest.main()
