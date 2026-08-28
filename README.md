# U of T Timetable Generator

A small desktop app that signs in to ACORN, loads your courses, and generates
conflict-free timetables from your preferences.

## Run

Python 3.10 or newer is required.

```bash
pip install -r requirements.txt
python gui.py
```

Click **Sign in to ACORN**, then complete UTORid and Duo sign-in in the Chrome
window. Credentials and cookies are not saved to disk.

The app reads ACORN's current-registration and timetable APIs. ACORN is an
internal service and may change its response format; this project is not
affiliated with the University of Toronto.
