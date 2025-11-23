# UofTCalandarGenerator

Headless Selenium script that signs in to **acorn.utoronto.ca**, captures **cookies** and **`X-XSRF-TOKEN`**, and optionally fetches your **current timetable / course codes** via ACORN’s REST endpoints.

## Features

- get_courses_info(True) returns just course codes
- get_courses_info(False) returns full activity objects

## Requirements

- Python **3.9+**
- Python packages: `selenium`, `requests`, `pyqt5`

## Install

```bash
pip install -r requirements.txt
pip install selenium requests
```

## Configure

In `config.py` configure your informations:

## Run

```python
python gui.py
```
