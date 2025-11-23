import sys
import datetime
import time
import os
import json

import requests
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QTextCursor, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from config import level_colors, level_emojis, gui_style, selenium_chrome_options

COOKIE_FILE = "acorn_cookies.json"


class LogTextEdit(QTextEdit):
    """DIY Log output colors + emoji"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)

        # Log colors
        self.level_colors = level_colors

        # emoji
        self.level_emojis = level_emojis

        # log text
        font = QFont("Consolas")
        font.setPointSize(10)
        self.setFont(font)

    def append_log(self, message: str, level: str = "info"):
        """append a message with color and timestamp and emoji"""
        color = self.level_colors.get(level, QColor("#333333"))
        emoji = self.level_emojis.get(level, "•")

        self.setTextColor(color)

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.append(f"[{timestamp}] {emoji} {message}")

        # move to the end
        self.moveCursor(QTextCursor.End)
        self.setTextColor(QColor("#333333"))  # set default color


class LoginWorker(QObject):
    """Selenium login in other threads"""

    log = pyqtSignal(str, str)  # message, level
    finished = pyqtSignal(object, object)  # cookies_dict, xsrf_token
    failed = pyqtSignal(str)  # error message

    def __init__(self, username: str, password: str, parent=None):
        super().__init__(parent)
        self.username = username
        self.password = password

    def run(self):
        chrome_options = Options()
        for o in selenium_chrome_options:
            chrome_options.add_argument(o)

        driver = webdriver.Chrome(options=chrome_options)

        cookies_dict = {}
        xsrf_token = None

        try:
            self.log.emit("Redirecting to login page...", "info")
            driver.get("https://acorn.utoronto.ca/")

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )

            # input username and pwd elements
            username_input = driver.find_element(By.ID, "username")
            password_input = driver.find_element(By.ID, "password")

            # username and password
            username_input.send_keys(self.username)
            password_input.send_keys(self.password)

            login_button = driver.find_element(By.NAME, "_eventId_proceed")
            login_button.click()
            time.sleep(0.5)
            current_url = driver.current_url
            if "idpz.utorauth.utoronto.ca" in current_url:
                self.log.emit("Your username or password is wrong!", "warning")
                self.failed.emit("Invalid credentials")
                return
            else:
                self.log.emit("Login submitted, waiting for Duo Mobile...", "info")

            # Duo / trust-browser step
            try:
                self.log.emit("Wating for user to pass Duo Mobile...", "info")
                trust_button = WebDriverWait(driver, 15).until(
                    EC.element_to_be_clickable((By.ID, "trust-browser-button"))
                )
                trust_button.click()
                self.log.emit("Duo Mobile passed.", "success")
            except TimeoutException as e:
                self.log.emit(f"Duo Mobile timeout : {e}", "warning")
                return

            try:
                WebDriverWait(driver, 60).until(EC.url_contains("/sws/"))
                self.log.emit("Redirected back to ACORN SWS.", "info")
            except TimeoutException:
                self.log.emit(
                    "Wait for ACORN main page timeout, continue anyway.", "warning"
                )

            # get cookies
            cookies = driver.get_cookies()
            cookies_dict = {cookie["name"]: cookie["value"] for cookie in cookies}

            # get X-XSRF-TOKEN
            if "XSRF-TOKEN" in cookies_dict:
                xsrf_token = cookies_dict["XSRF-TOKEN"]
                self.log.emit("X-XSRF-TOKEN fetched successfully.", "success")
            else:
                self.log.emit("Can't find XSRF-TOKEN in cookies.", "error")
                self.log.emit(str(cookies_dict), "error")
                self.failed.emit("XSRF token not found")
                return

            self.finished.emit(cookies_dict, xsrf_token)

        except Exception as e:
            self.log.emit(f"Error while login: {str(e)}", "error")
            self.failed.emit(str(e))
        finally:
            driver.quit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UofT Timetable Generator")
        self.resize(900, 500)

        self.cookies_dict = None
        self.xsrf_token = None
        self.thread = None
        self.worker = None
        self.current_username = None

        self.cookie_store = self.load_cookie_store()

        # GUI styles
        self.setStyleSheet(gui_style)

        # center Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Username & password panel
        account_group = QGroupBox("Login Infos")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)

        username_label = QLabel("Username:")
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("UTORid / JOINid")

        password_label = QLabel("Password:")
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Please input your password")
        self.password_edit.setEchoMode(QLineEdit.Password)

        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self.handle_login)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.login_button)

        # Layout
        grid.addWidget(username_label, 0, 0)
        grid.addWidget(self.username_edit, 0, 1)
        grid.addWidget(password_label, 1, 0)
        grid.addWidget(self.password_edit, 1, 1)
        grid.addLayout(btn_layout, 2, 0, 1, 2)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        account_group.setLayout(grid)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(account_group)
        left_layout.addStretch()
        left_layout.setSpacing(15)

        # Log widgets
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()
        self.log_widget = LogTextEdit()
        log_layout.addWidget(self.log_widget)
        log_group.setLayout(log_layout)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(log_group)
        right_layout.setContentsMargins(0, 0, 0, 0)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 2)

        central_widget.setLayout(main_layout)

        self.log_widget.append_log("This is a UofT timetable generator.", "info")
        self.log_widget.append_log(
            "Please input your UTORid and password to login.", "info"
        )

    def load_cookie_store(self) -> dict:
        """Load cookie cache from local file"""
        if not os.path.exists(COOKIE_FILE):
            return {}
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
        except Exception:

            return {}

    def save_cookie_store(self):
        """Save cookie cache to local file"""
        try:
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cookie_store, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_widget.append_log(
                f"Failed to save cookie file: {str(e)}", "warning"
            )

    def try_use_cached_session(self, username: str) -> bool:
        """use local cookies cache if still valid."""
        user_entry = self.cookie_store.get(username)
        if not user_entry:
            self.log_widget.append_log(
                "No saved cookies found for this user, will login.", "debug"
            )
            return False

        cookies_dict = user_entry.get("cookies") or {}
        xsrf_token = user_entry.get("xsrf_token")

        if not cookies_dict or not xsrf_token:
            self.log_widget.append_log(
                "Saved cookies are incomplete, will login again.", "warning"
            )
            return False

        self.log_widget.append_log(
            "Found saved cookies, trying to reuse session...", "info"
        )

        try:
            session = requests.Session()
            session.cookies.update(cookies_dict)

            headers = {"X-XSRF-TOKEN": xsrf_token}
            test_url = (
                "https://acorn.utoronto.ca/sws/rest/enrolment/current-registrations"
            )
            resp = session.get(test_url, headers=headers, timeout=10)

            if resp.status_code == 200:
                self.log_widget.append_log(
                    "Saved session is still valid, login skipped.", "success"
                )
                self.cookies_dict = cookies_dict
                self.xsrf_token = xsrf_token
                return True
            else:
                self.log_widget.append_log(
                    f"Saved session invalid (HTTP {resp.status_code}), re-login needed.",
                    "warning",
                )
                return False
        except Exception as e:
            self.log_widget.append_log(
                f"Failed to reuse cookies, will login again: {str(e)}", "warning"
            )
            return False

    def handle_login(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()

        if not username or not password:
            self.log_widget.append_log(
                "Username or password can't be empty.", "warning"
            )
            return

        self.current_username = username

        # try use local cookies
        if self.try_use_cached_session(username):
            # if still valid no need to login and get cookies again.
            return

        self.log_widget.append_log(f"Trying to login: {username}", "info")

        self.login_button.setEnabled(False)

        # Create threads worker
        self.thread = QThread(self)
        self.worker = LoginWorker(username, password)
        self.worker.moveToThread(self.thread)

        # start worker.run
        self.thread.started.connect(self.worker.run)

        # connect to log signal
        self.worker.log.connect(self.log_widget.append_log)

        # handle sucess and failed
        self.worker.finished.connect(self.on_login_finished)
        self.worker.failed.connect(self.on_login_failed)

        # quit threads
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: self.login_button.setEnabled(True))

        self.thread.start()

    def on_login_finished(self, cookies_dict, xsrf_token):
        """finished callback"""
        self.cookies_dict = cookies_dict
        self.xsrf_token = xsrf_token

        # cookies cache
        if self.current_username:
            self.cookie_store[self.current_username] = {
                "cookies": cookies_dict,
                "xsrf_token": xsrf_token,
                "saved_at": datetime.datetime.now().isoformat(),
            }
            self.save_cookie_store()
            self.log_widget.append_log(
                "Cookies saved locally for future logins.", "success"
            )

        self.log_widget.append_log(
            "Login finished. Cookies and XSRF token saved.", "success"
        )

    def on_login_failed(self, msg: str):
        """failed callback"""
        self.log_widget.append_log(f"Login failed: {msg}", "error")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
