import math
import random
import sys

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils import (
    DAY_NAMES,
    CourseNotFound,
    apply_pins,
    blocked_groups,
    clock,
    decode_pins,
    encode_pins,
    fetch_many,
    fetch_offerings,
    generate_timetables,
    group_sections,
    load_config,
    normalize_code,
    save_config,
    search_courses,
    section_summary,
    session_label,
)

MAX_SCHEDULES = 20
SEARCH_DELAY_MS = 300
ANY_SECTION = "Any section"

STYLE = """
QWidget { font: 13px "Segoe UI"; color: #202124; }
QMainWindow { background: #f6f7f9; }
QGroupBox { background: white; border: 1px solid #dfe1e5; border-radius: 6px;
            margin-top: 10px; padding-top: 10px; }
QGroupBox::title { left: 10px; padding: 0 4px; font-weight: 600; }
QPushButton { background: #1a73e8; color: white; border: 0; border-radius: 4px;
              padding: 8px 14px; }
QPushButton:disabled { background: #aeb8c4; }
QComboBox, QLineEdit { background: white; border: 1px solid #dfe1e5;
                       border-radius: 4px; padding: 5px; }
QListWidget { background: white; border: 1px solid #dfe1e5; border-radius: 4px; }
QListWidget::item:selected { background: #e8f0fe; color: #174ea6; }
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
                f"{clock(meeting.start)}–{clock(meeting.end)}{location}"
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


class Task(QObject):
    """Runs one callable on a worker thread and reports back by signal."""

    done = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, sequence, work):
        super().__init__()
        self.sequence = sequence
        self.work = work

    def run(self):
        try:
            self.done.emit(self.sequence, self.work())
        except CourseNotFound as error:
            self.failed.emit(self.sequence, str(error))
        except Exception as error:
            self.failed.emit(
                self.sequence, f"Could not reach Timetable Builder: {error}"
            )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("U of T Timetable Generator")
        self.resize(1100, 860)
        self.setStyleSheet(STYLE)

        self.offerings = []
        self.pins = {}
        self.schedules = []
        self.index = 0
        self.jobs = []
        self.search_sequence = 0
        self.pending_courses = 0

        self.build_ui()
        self.restore()

    # -- layout ---------------------------------------------------------

    def build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self.setCentralWidget(root)

        self.status = QLabel("Type a course code or title to search the catalogue.")
        layout.addWidget(self.status)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self.build_course_panel(), 1)
        columns.addWidget(self.build_section_panel(), 1)
        layout.addLayout(columns)

        layout.addWidget(self.build_preference_panel())

        self.view_title = QLabel("No timetable yet.")
        self.view_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self.view_title)
        self.timetable = TimetableWidget()
        layout.addWidget(self.timetable, 1)

    def build_course_panel(self):
        box = QGroupBox("Courses")
        panel = QVBoxLayout(box)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search, e.g. M, MGEA, or calculus")
        self.search_input.textEdited.connect(self.search_later)
        self.search_input.returnPressed.connect(self.add_highlighted)
        panel.addWidget(self.search_input)

        self.results = QListWidget()
        self.results.setMaximumHeight(150)
        self.results.itemActivated.connect(self.add_match)
        self.results.itemDoubleClicked.connect(self.add_match)
        self.results.hide()
        panel.addWidget(self.results)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.search)

        panel.addWidget(QLabel("Added courses"))
        self.course_list = QListWidget()
        self.course_list.setMaximumHeight(130)
        panel.addWidget(self.course_list)

        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self.remove_course)
        panel.addWidget(self.remove_button)
        return box

    def build_section_panel(self):
        box = QGroupBox("Sections")
        panel = QVBoxLayout(box)
        panel.addWidget(
            QLabel("Pin a section, or leave it to the generator.")
        )
        self.section_table = QTableWidget(0, 3)
        self.section_table.setHorizontalHeaderLabels(["Course", "Type", "Section"])
        self.section_table.verticalHeader().hide()
        self.section_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.section_table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.section_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        panel.addWidget(self.section_table, 1)
        return box

    def build_preference_panel(self):
        box = QGroupBox("Preferences")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("Session"), 0, 0)
        self.session = QComboBox()
        self.session.currentIndexChanged.connect(self.select_session)
        grid.addWidget(self.session, 0, 1, 1, 5)

        grid.addWidget(QLabel("Days off"), 1, 0)
        self.day_boxes = []
        for column, day in enumerate(DAY_NAMES, start=1):
            check = QCheckBox(day[:3])
            check.stateChanged.connect(self.remember)
            self.day_boxes.append(check)
            grid.addWidget(check, 1, column)

        grid.addWidget(QLabel("Earliest class"), 2, 0)
        self.earliest = QComboBox()
        self.earliest.addItem("No limit", None)
        for hour in range(8, 17):
            self.earliest.addItem(f"{hour:02d}:00", hour * 60)
        self.earliest.currentIndexChanged.connect(self.remember)
        grid.addWidget(self.earliest, 2, 1, 1, 2)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setEnabled(False)
        self.generate_button.clicked.connect(self.generate)
        grid.addWidget(self.generate_button, 2, 3)

        self.previous_button = QPushButton("◀ Previous")
        self.previous_button.setEnabled(False)
        self.previous_button.clicked.connect(lambda: self.step(-1))
        grid.addWidget(self.previous_button, 2, 4)

        self.next_button = QPushButton("Next ▶")
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(lambda: self.step(1))
        grid.addWidget(self.next_button, 2, 5)

        self.export_button = QPushButton("Export PNG")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_png)
        grid.addWidget(self.export_button, 3, 5)
        return box

    # -- background work ------------------------------------------------

    def run(self, work, on_done, on_failed, sequence=0):
        thread = QThread(self)
        task = Task(sequence, work)
        task.moveToThread(thread)
        thread.started.connect(task.run)
        task.done.connect(on_done)
        task.failed.connect(on_failed)
        task.done.connect(thread.quit)
        task.failed.connect(thread.quit)
        thread.finished.connect(lambda: self.job_finished(thread, task))
        self.jobs.append((thread, task))
        thread.start()

    def job_finished(self, thread, task):
        self.jobs = [job for job in self.jobs if job[0] is not thread]
        task.deleteLater()
        thread.deleteLater()

    # -- search ---------------------------------------------------------

    def search_later(self, _text):
        self.search_timer.start(SEARCH_DELAY_MS)

    def search(self):
        term = self.search_input.text().strip()
        if not term:
            self.results.clear()
            self.results.hide()
            return

        self.search_sequence += 1
        self.run(
            lambda: search_courses(term),
            self.search_ready,
            self.search_failed,
            self.search_sequence,
        )

    def search_ready(self, sequence, matches):
        # A slower earlier search must not overwrite newer results.
        if sequence != self.search_sequence:
            return
        self.results.clear()
        added = {offering.code for offering in self.offerings}
        for match in matches:
            suffix = "  (added)" if match.code in added else ""
            self.results.addItem(match.label + suffix)
            self.results.item(self.results.count() - 1).setData(
                Qt.UserRole, match.code
            )
        self.results.setVisible(bool(matches))
        if not matches:
            self.status.setText("No course matches that search.")

    def search_failed(self, sequence, message):
        if sequence == self.search_sequence:
            self.status.setText(message)

    def add_highlighted(self):
        item = self.results.currentItem() or self.results.item(0)
        if item:
            self.add_match(item)
        else:
            self.add_code(normalize_code(self.search_input.text()))

    def add_match(self, item):
        self.add_code(item.data(Qt.UserRole))

    # -- course list ----------------------------------------------------

    def add_code(self, code):
        code = normalize_code(code)
        if not code:
            return
        if any(offering.code == code for offering in self.offerings):
            self.status.setText(f"{code} is already added.")
            return

        self.pending_courses += 1
        self.status.setText(f"Loading {code}...")
        self.run(
            lambda: fetch_offerings(code),
            self.course_loaded,
            self.course_failed,
        )

    def course_loaded(self, _sequence, offerings):
        self.pending_courses -= 1
        self.offerings.extend(offerings)
        self.search_input.clear()
        self.results.clear()
        self.results.hide()

        code = offerings[0].code
        sessions = sorted({offering.session for offering in offerings})
        self.status.setText(
            f"Added {code} — offered in "
            + ", ".join(session_label(session) for session in sessions)
            + "."
        )
        self.refresh_courses()
        self.refresh_sessions()
        self.remember()

    def course_failed(self, _sequence, message):
        self.pending_courses -= 1
        self.status.setText(message)

    def remove_course(self):
        item = self.course_list.currentItem()
        if not item:
            self.status.setText("Select a course in the list first.")
            return
        code = item.data(Qt.UserRole)
        self.offerings = [
            offering for offering in self.offerings if offering.code != code
        ]
        self.pins = {
            key: value
            for key, value in self.pins.items()
            if key[0].split()[0] != code
        }
        self.status.setText(f"Removed {code}.")
        self.refresh_courses()
        self.refresh_sessions()
        self.remember()

    def refresh_courses(self):
        self.course_list.clear()
        seen = set()
        for offering in self.offerings:
            if offering.code in seen:
                continue
            seen.add(offering.code)
            self.course_list.addItem(offering.label)
            self.course_list.item(self.course_list.count() - 1).setData(
                Qt.UserRole, offering.code
            )

    # -- session and sections -------------------------------------------

    def refresh_sessions(self, preferred=None):
        target = self.session.currentData() if preferred is None else preferred
        self.session.blockSignals(True)
        self.session.clear()
        for session in sorted({offering.session for offering in self.offerings}):
            self.session.addItem(session_label(session), session)
        if target is not None:
            restored = self.session.findData(target)
            if restored >= 0:
                self.session.setCurrentIndex(restored)
        self.session.blockSignals(False)
        self.select_session(self.session.currentIndex())

    def selected_offerings(self):
        session = self.session.currentData()
        return [offering for offering in self.offerings if offering.session == session]

    def select_session(self, _index):
        self.schedules = []
        self.index = 0
        self.timetable.show_schedule([])
        self.update_navigation()
        self.refresh_sections()

        offerings = self.selected_offerings()
        self.generate_button.setEnabled(bool(offerings))
        if not offerings:
            self.view_title.setText("No timetable yet.")
            return

        missing = {offering.code for offering in self.offerings} - {
            offering.code for offering in offerings
        }
        note = f" ({', '.join(sorted(missing))} not offered)" if missing else ""
        self.view_title.setText(
            f"{len(offerings)} course(s) in {self.session.currentText()}{note}."
            " Choose Generate."
        )
        self.remember()

    def refresh_sections(self):
        groups = group_sections(self.selected_offerings())
        self.section_table.setRowCount(len(groups))
        for row, ((course, activity), sections) in enumerate(groups.items()):
            self.section_table.setItem(row, 0, QTableWidgetItem(course))
            self.section_table.setItem(row, 1, QTableWidgetItem(activity))

            chooser = QComboBox()
            chooser.addItem(f"{ANY_SECTION} ({len(sections)})", None)
            for section in sorted(sections, key=lambda item: item.code):
                chooser.addItem(
                    f"{section.code} — {section_summary(section)}", section.code
                )
            pinned = chooser.findData(self.pins.get((course, activity)))
            chooser.setCurrentIndex(max(0, pinned))
            chooser.currentIndexChanged.connect(
                lambda _index, key=(course, activity), widget=chooser: self.pin(
                    key, widget.currentData()
                )
            )
            self.section_table.setCellWidget(row, 2, chooser)

    def pin(self, key, code):
        if code:
            self.pins[key] = code
        else:
            self.pins.pop(key, None)
        self.remember()

    # -- generation -----------------------------------------------------

    def generate(self):
        groups = apply_pins(group_sections(self.selected_offerings()), self.pins)
        days_off = {
            index for index, box in enumerate(self.day_boxes) if box.isChecked()
        }
        earliest = self.earliest.currentData()
        self.schedules = generate_timetables(
            groups, days_off, earliest, limit=MAX_SCHEDULES
        )
        self.index = 0

        if not self.schedules:
            self.timetable.show_schedule([])
            self.update_navigation()
            blocked = blocked_groups(groups, days_off, earliest)
            if blocked:
                names = ", ".join(
                    f"{course} {activity}" for course, activity in blocked
                )
                self.view_title.setText(f"No section of {names} fits these preferences.")
            else:
                self.view_title.setText(
                    "Every combination of these sections has a time conflict."
                )
            return

        options = ", ".join(
            f"{course} {activity} ×{len(sections)}"
            for (course, activity), sections in groups.items()
        )
        self.status.setText(f"Section choices — {options}")
        self.show_current()

    def step(self, delta):
        self.index = (self.index + delta) % len(self.schedules)
        self.show_current()

    def show_current(self):
        self.timetable.show_schedule(self.schedules[self.index])
        self.view_title.setText(
            f"{self.session.currentText()} · Schedule {self.index + 1}"
            f" of {len(self.schedules)}"
        )
        self.update_navigation()

    def update_navigation(self):
        has_many = len(self.schedules) > 1
        self.previous_button.setEnabled(has_many)
        self.next_button.setEnabled(has_many)
        self.export_button.setEnabled(bool(self.schedules))

    def export_png(self):
        name = (
            f"{self.session.currentText()}-schedule-{self.index + 1}"
            .replace(" ", "-")
            .replace("/", "-")
            .replace("(", "")
            .replace(")", "")
        )
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

    # -- saved state ----------------------------------------------------

    def restore(self):
        config = load_config()
        self.pins = decode_pins(config.get("pins"))
        self.pending_session = config.get("session")

        for index, box in enumerate(self.day_boxes):
            box.blockSignals(True)
            box.setChecked(index in set(config.get("days_off") or []))
            box.blockSignals(False)
        earliest = self.earliest.findData(config.get("earliest"))
        if earliest >= 0:
            self.earliest.blockSignals(True)
            self.earliest.setCurrentIndex(earliest)
            self.earliest.blockSignals(False)

        codes = [code for code in config.get("courses") or [] if isinstance(code, str)]
        if not codes:
            self.pending_session = None
            return
        self.status.setText(f"Restoring {len(codes)} saved course(s)...")
        self.pending_courses += 1
        self.run(lambda: fetch_many(codes), self.courses_restored, self.course_failed)

    def courses_restored(self, _sequence, result):
        self.pending_courses -= 1
        offerings, failed = result
        self.offerings.extend(offerings)
        self.refresh_courses()
        self.refresh_sessions(self.pending_session)
        self.pending_session = None

        restored_count = len({offering.code for offering in offerings})
        message = f"Restored {restored_count} saved course(s)."
        if failed:
            message += f" Could not load {', '.join(failed)}."
        self.status.setText(message)

    def remember(self):
        # Nothing is saved until the restore fetch has settled, so a failed
        # start-up lookup cannot quietly erase the saved list.
        if self.pending_courses:
            return
        save_config(
            {
                "courses": sorted({offering.code for offering in self.offerings}),
                "session": self.session.currentData(),
                "pins": encode_pins(self.pins),
                "days_off": sorted(
                    index
                    for index, box in enumerate(self.day_boxes)
                    if box.isChecked()
                ),
                "earliest": self.earliest.currentData(),
            }
        )

    def closeEvent(self, event):
        self.remember()
        for thread, _task in list(self.jobs):
            thread.quit()
            thread.wait(2000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
