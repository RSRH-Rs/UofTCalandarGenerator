import math
import random
import sys

from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from utils import (
    AcornClient,
    DAY_NAMES,
    clear_session,
    extract_sections,
    generate_timetables,
    load_session,
    save_session,
    session_token,
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
QComboBox { background: white; border: 1px solid #dfe1e5;
            border-radius: 4px; padding: 5px; }
QTableWidget { background: white; border: 1px solid #dfe1e5; gridline-color: #e8eaed; }
QTableWidget::item { padding: 3px; }
QHeaderView::section { background: #f8f9fa; border: 0; border-right: 1px solid #dfe1e5;
                       border-bottom: 1px solid #dfe1e5; padding: 6px; font-weight: 600; }
"""

COLORS = (
    "#c94472",
    "#7651bd",
    "#159b75",
    "#dc593e",
    "#dc8c25",
    "#3678b8",
    "#8d5a9e",
    "#3b8f5a",
)


class TimetableWidget(QTableWidget):
    def __init__(self):
        super().__init__()
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(DAY_NAMES)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.verticalHeader().setFixedWidth(60)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setTextElideMode(Qt.ElideNone)
        self.setWordWrap(True)
        self.show_schedule([])

    def show_schedule(self, schedule):
        meetings = [
            (meeting, section)
            for section in schedule
            for meeting in section.meetings
        ]
        start_hour = max(7, min((item[0].start // 60 for item in meetings), default=8))
        end_hour = min(
            23,
            max((math.ceil(item[0].end / 60) for item in meetings), default=18),
        )
        self.clearSpans()
        self.clearContents()
        self.setRowCount((end_hour - start_hour) * 2)
        self.setVerticalHeaderLabels(
            [
                f"{start_hour + row // 2}:00" if row % 2 == 0 else ""
                for row in range(self.rowCount())
            ]
        )
        for row in range(self.rowCount()):
            self.setRowHeight(row, 32)

        palette = list(COLORS)
        random.shuffle(palette)
        course_colors = {}
        for meeting, section in sorted(
            meetings, key=lambda item: (item[0].day, item[0].start)
        ):
            row = (meeting.start - start_hour * 60) // 30
            if not 0 <= meeting.day < 5 or not 0 <= row < self.rowCount():
                continue
            span = min(
                max(1, math.ceil((meeting.end - meeting.start) / 30)),
                self.rowCount() - row,
            )
            color = course_colors.setdefault(
                section.course,
                palette[len(course_colors) % len(palette)],
            )
            location = f"\n{meeting.location}" if meeting.location else ""
            item = QTableWidgetItem(
                f"{section.course} · {section.code}\n"
                f"{_clock(meeting.start)}–{_clock(meeting.end)}{location}"
            )
            item.setBackground(QColor(color))
            item.setForeground(QColor("white"))
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.setSpan(row, meeting.day, span, 1)
            self.setItem(row, meeting.day, item)

    def save_png(self, path, title):
        old_size = self.size()
        old_minimum = self.minimumSize()
        old_maximum = self.maximumSize()
        old_vertical = self.verticalScrollBarPolicy()
        old_horizontal = self.horizontalScrollBarPolicy()
        height = (
            self.horizontalHeader().height()
            + sum(self.rowHeight(row) for row in range(self.rowCount()))
            + self.frameWidth() * 2
        )

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedSize(old_size.width(), height)
        QApplication.processEvents()
        table_image = QPixmap(self.size())
        table_image.fill(Qt.white)
        self.render(table_image)

        image = QPixmap(table_image.width(), table_image.height() + 52)
        image.fill(Qt.white)
        painter = QPainter(image)
        font = painter.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(16, 0, image.width() - 32, 52, Qt.AlignVCenter, title)
        painter.drawPixmap(0, 52, table_image)
        painter.end()
        saved = image.save(path, "PNG")

        self.setMinimumSize(old_minimum)
        self.setMaximumSize(old_maximum)
        self.resize(old_size)
        self.setVerticalScrollBarPolicy(old_vertical)
        self.setHorizontalScrollBarPolicy(old_horizontal)
        QApplication.processEvents()
        return saved


def _clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class LoginWorker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        cached = load_session()
        if cached:
            try:
                sessions = AcornClient(cached, session_token(cached)).fetch_courses()
                self.finished.emit({"sessions": sessions, "cached": True})
                return
            except Exception:
                clear_session()

        options = Options()
        options.add_argument("--disable-notifications")
        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            driver.get("https://acorn.utoronto.ca/")

            # The logout link only appears after ACORN authentication finishes.
            WebDriverWait(driver, 300).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'a[href="auth/logout"]')
                )
            )
            cookies = driver.get_cookies()
            sessions = AcornClient(cookies, session_token(cookies)).fetch_courses()
            save_session(cookies)
            self.finished.emit({"sessions": sessions, "cached": False})
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if driver:
                driver.quit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("U of T Timetable Generator")
        self.resize(980, 720)
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

        self.status = QLabel("Load your ACORN courses.")
        self.login_button = QPushButton("Load courses")
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

        self.view_button = QPushButton("View my courses")
        self.view_button.setEnabled(False)
        self.view_button.clicked.connect(self.view_courses)
        grid.addWidget(self.view_button, 2, 3)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self.generate)
        grid.addWidget(self.generate_button, 2, 4)

        self.export_button = QPushButton("Export PNG")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_png)
        grid.addWidget(self.export_button, 2, 5)
        layout.addWidget(preferences)

        self.view_title = QLabel("Load courses to view your timetable.")
        self.view_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self.view_title)
        self.timetable = TimetableWidget()
        layout.addWidget(self.timetable, 1)

    def login(self):
        self.login_button.setEnabled(False)
        self.status.setText("Checking saved session...")

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

    def login_finished(self, result):
        sessions = result["sessions"]
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
            f"Loaded {len(courses)} courses in {len(self.periods)} periods"
            f" using {'saved session' if result['cached'] else 'new login'}."
        )
        self.login_button.setEnabled(True)
        self.select_period(self.session.currentIndex())
        if not self.periods:
            self.view_title.setText(
                "ACORN returned courses, but no meeting times were recognized."
            )

    def select_period(self, index):
        self.groups = self.periods[index] if 0 <= index < len(self.periods) else {}
        self.generate_button.setEnabled(bool(self.groups))
        self.view_button.setEnabled(bool(self.groups))
        self.export_button.setEnabled(False)
        self.timetable.show_schedule([])
        if self.groups:
            self.view_title.setText("Choose View my courses or Generate.")

    def login_failed(self, message):
        self.status.setText("Sign-in or course loading failed.")
        self.view_title.setText(message)
        self.login_button.setEnabled(True)

    def view_courses(self):
        schedule = [sections[0] for sections in self.groups.values() if sections]
        self.timetable.show_schedule(schedule)
        self.export_button.setEnabled(bool(schedule))
        self.view_title.setText(f"{self.session.currentText()} · My courses")

    def generate(self):
        days_off = {
            index for index, box in enumerate(self.day_boxes) if box.isChecked()
        }
        schedules = generate_timetables(
            self.groups, days_off, self.earliest.currentData(), limit=1
        )
        if not schedules:
            self.timetable.show_schedule([])
            self.export_button.setEnabled(False)
            self.view_title.setText(
                "No conflict-free timetable matches these preferences."
            )
            return
        self.timetable.show_schedule(schedules[0])
        self.export_button.setEnabled(True)
        self.view_title.setText(f"{self.session.currentText()} · Generated timetable")

    def export_png(self):
        name = self.session.currentText().replace(" · ", "-").replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export timetable", f"{name}.png", "PNG image (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if self.timetable.save_png(path, self.view_title.text()):
            self.status.setText(f"Timetable exported to {path}")
        else:
            self.status.setText("Could not export the timetable.")

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
