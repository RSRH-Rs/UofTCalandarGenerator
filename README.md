# UofTCalandarGenerator

Headless Selenium script that signs in to **acorn.utoronto.ca**, captures **cookies** and **`X-XSRF-TOKEN`**, and optionally fetches your **current timetable / course codes** via ACORN’s REST endpoints.

## Features

- Automated Chrome login (headless by default)
- Extracts cookies and `X-XSRF-TOKEN`
- `get_courses_info(only_course_code=True)` returns just course codes
- `get_courses_info(False)` returns full activity objects

## Requirements

- Python **3.9+**
- **Google Chrome** installed
- **ChromeDriver** matching your Chrome version and available on `PATH`
- Python packages: `selenium`, `requests`

## Install

```bash
pip install -r requirements.txt
pip install selenium requests
```

## Configure

In `config.py` configure your informations:

```python
# config.py
import os

# Prefer environment variables; fall back to hard-coded strings if needed.
UTUSERNAME = "your_utorid"
UTPASSWORD = "your_password"
```

## Run

```python
python acorn_tokens_and_courses.py
```
