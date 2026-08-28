import sys

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from utils import (
    AcornClient,
    DAY_NAMES,
    extract_sections,
    format_timetable,
    generate_timetables,
    split_periods,
)

STYLE = """
QWidget { font: 13px "Segoe UI"; color: #202124; }
QMainWindow { background: #f6f7f9; }
QGroupBox { background: white; border: 1px solid #dfe1e5; border-radius: 6px;
            margin-top: 10px; padding-top: 10px; }
QGroupBox::title { left: 10px; padding: 0 4px; font-weight: 600; }
QPushButton { background: #1a73e8; color: white; border: 0; border-radius: 4px;
              padding: 8px 14px; }
QPushButton:disabled { background: #aeb8c4; }
QComboBox, QTextEdit { background: white; border: 1px solid #dfe1e5;
                       border-radius: 4px; padding: 5px; }
"""


class LoginWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        options = Options()
        options.add_argument("--disable-notifications")
        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.get("https://acorn.utoronto.ca/")

            # The user completes UTORid and Duo in the browser.
            WebDriverWait(driver, 300).until(
                lambda browser: "/sws/" in browser.current_url
                and any(
                    cookie["name"] == "XSRF-TOKEN" for cookie in browser.get_cookies()
                )
            )
            cookies = {
                cookie["name"]: cookie["value"] for cookie in driver.get_cookies()
            }
            payloads = AcornClient(cookies, cookies["XSRF-TOKEN"]).fetch_courses()
            self.finished.emit(payloads)
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if driver:
                driver.quit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("U of T Timetable Generator")
        self.resize(720, 620)
        self.setStyleSheet(STYLE)
        self.groups = {}
        self.periods = []
        self.thread = None
        self.worker = None

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.setCentralWidget(root)

        self.status = QLabel("Sign in to ACORN to load your courses.")
        self.login_button = QPushButton("Sign in to ACORN")
        self.login_button.clicked.connect(self.login)
        layout.addWidget(self.status)
        layout.addWidget(self.login_button)

        preferences = QGroupBox("Preferences")
        grid = QGridLayout(preferences)
        grid.addWidget(QLabel("Session"), 0, 0)
        self.session = QComboBox()
        self.session.currentIndexChanged.connect(self.select_period)
        grid.addWidget(self.session, 0, 1, 1, 5)

        grid.addWidget(QLabel("Days off"), 1, 0)
        self.day_boxes = []
        for column, day in enumerate(DAY_NAMES, start=1):
            box = QCheckBox(day[:3])
            self.day_boxes.append(box)
            grid.addWidget(box, 1, column)

        grid.addWidget(QLabel("Earliest class"), 2, 0)
        self.earliest = QComboBox()
        self.earliest.addItem("No limit", None)
        for hour in range(9, 16):
            self.earliest.addItem(f"{hour:02d}:00", hour * 60)
        grid.addWidget(self.earliest, 2, 1, 1, 2)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self.generate)
        grid.addWidget(self.generate_button, 2, 4, 1, 2)
        layout.addWidget(preferences)

        self.results = QTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("Generated timetables will appear here.")
        layout.addWidget(self.results, 1)

    def login(self):
        self.login_button.setEnabled(False)
        self.status.setText("Complete UTORid and Duo sign-in in the Chrome window...")

        self.thread = QThread(self)
        self.worker = LoginWorker()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.login_finished)
        self.worker.failed.connect(self.login_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def login_finished(self, sessions):
        self.periods = []
        self.session.clear()
        courses = set()
        for session in sessions:
            groups = extract_sections(session["data"])
            courses.update(course for course, _ in groups)
            for period_name, period_groups in split_periods(groups):
                self.periods.append(period_groups)
                self.session.addItem(f"{session['label']} · {period_name}")

        self.status.setText(
            f"Loaded {len(courses)} courses in {len(self.periods)} periods."
        )
        self.login_button.setEnabled(True)
        self.select_period(self.session.currentIndex())
        if not self.periods:
            self.results.setPlainText(
                "ACORN returned courses, but no meeting times were recognized."
            )

    def select_period(self, index):
        self.groups = self.periods[index] if 0 <= index < len(self.periods) else {}
        self.generate_button.setEnabled(bool(self.groups))

    def login_failed(self, message):
        self.status.setText("Sign-in or course loading failed.")
        self.results.setPlainText(message)
        self.login_button.setEnabled(True)

    def generate(self):
        days_off = {
            index for index, box in enumerate(self.day_boxes) if box.isChecked()
        }
        schedules = generate_timetables(
            self.groups, days_off, self.earliest.currentData(), limit=20
        )
        if not schedules:
            self.results.setPlainText(
                "No conflict-free timetable matches these preferences."
            )
            return
        self.results.setPlainText(
            "\n\n".join(
                format_timetable(schedule, index)
                for index, schedule in enumerate(schedules, start=1)
            )
        )

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            self.status.setText("Close the ACORN Chrome window before exiting.")
            event.ignore()
            return
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
