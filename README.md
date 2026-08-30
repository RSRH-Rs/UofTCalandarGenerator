# U of T Timetable Generator

A small desktop app that searches the public U of T Timetable Builder
catalogue and generates conflict-free timetables from every offered section.

No sign-in, no ACORN, no personal data: the app only issues anonymous GET
requests to the same public API that <https://ttb.utoronto.ca> uses.

## Run

Python 3.10 or newer is required.

```bash
pip install -r requirements.txt
python gui.py
```

## Using it

**Search.** Start typing in the search box — a code fragment (`M`, `MGEA`), a
full code, or words from a title (`calculus`). Matches appear as you type;
press Enter or double-click one to add that course.

**Pin sections.** The *Sections* table lists every activity of every added
course — one row per lecture, tutorial and practical group. Leave a row on
*Any section* to let the generator choose, or pick a specific section to lock
it in. Pinning your tutorial and letting the lectures float is the usual case.

**Generate.** Pick a **Session**, set **Days off** and **Earliest class**, then
click **Generate**. Only the selected session's offerings are used, so a Summer
and a Fall offering of the same course are never mixed. Use **◀ Previous** /
**Next ▶** to browse alternatives and **Export PNG** to save one.

Choose **Any 1 day** under **Days off** when the particular weekday does not
matter. The generator will keep at least one Monday-to-Friday day class-free.
Choosing it clears and temporarily disables the specific weekday choices.

Timetables are ranked by fewest days on campus, then by least time spent
waiting between classes.

**Your list is remembered.** Added courses, pinned sections, the chosen session
and the preferences are saved automatically and restored on the next launch —
in `%LOCALAPPDATA%\UofT-Timetable-Generator\courses.json` for the packaged
build, or `.ttb_courses.json` beside the source when run from Python. Delete
that file to start over.

## Limits

The generator picks one section per course activity (one LEC, one TUT, one
PRA). Some courses restrict which tutorial you may take with a given lecture;
the API does not expose that linkage, so verify a generated timetable in ACORN
before enrolling. Asynchronous online sections are kept as choices but occupy
no timetable slot. TBA sections without usable scheduling information and
cancelled sections are skipped.

A search over more than a few large courses can have billions of combinations.
The search backtracks out of conflicting branches and stops after
`MAX_SEARCH_STEPS` steps or `MAX_CANDIDATES` complete timetables, so for very
large searches the ranked results are the best of a sample rather than of every
possibility. Pinning sections narrows the search and makes the ranking exact.

This project is not affiliated with the University of Toronto, and the
Timetable Builder API is undocumented and may change.
