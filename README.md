# U of T Timetable Generator

A small desktop app that signs in to ACORN, loads your courses, and generates
conflict-free timetables from your preferences.

## Run

Python 3.10 or newer is required.

```bash
pip install -r requirements.txt
python gui.py
```

Click **Load courses**. The app reuses `.acorn_session.json` when the saved
session is valid; otherwise, complete UTORid and Duo sign-in in Chrome. The
password is never stored. Delete `.acorn_session.json` to forget the session.

Use **View my courses** to display every meeting returned for your enrolled
activities. **Generate** applies the selected days off and earliest class time,
then displays the best matching timetable in a weekly grid. **Export PNG** saves
the complete timetable, including rows outside the visible scroll area.

The app reads ACORN's current-registration and timetable APIs. ACORN is an
internal service and may change its response format; this project is not
affiliated with the University of Toronto.
