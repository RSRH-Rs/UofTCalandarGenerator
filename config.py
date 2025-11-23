from PyQt5.QtGui import QColor

selenium_chrome_options = ["--headless", "--disable-gpu", "--disable-notifications"]
level_colors = {
    "info": QColor("#333333"),  # deep gray
    "success": QColor("#008000"),  # green
    "warning": QColor("#d49b00"),  # yellow
    "error": QColor("#cc0000"),  # red
    "debug": QColor("#888888"),  # grey
}
level_emojis = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
    "debug": "🐞",
}

gui_style = """
            QMainWindow {
                background-color: #f4f6fb;
            }
            QWidget {
                font-family: "Microsoft Yahei", "Segoe UI", sans-serif;
                font-size: 13px;
                color: #333333;
            }
            QGroupBox {
                border: 1px solid #d0d7e2;
                border-radius: 8px;
                margin-top: 10px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #3b4256;
                font-weight: 600;
            }
            QLabel {
                color: #3b4256;
            }
            QLineEdit {
                border: 1px solid #c0c6d4;
                border-radius: 4px;
                padding: 5px 8px;
                background-color: #fbfcff;
            }
            QLineEdit:focus {
                border: 1px solid #4c6fff;
                background-color: #ffffff;
            }
            QPushButton {
                background-color: #4c6fff;
                border-radius: 6px;
                color: white;
                padding: 6px 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3c58d6;
            }
            QPushButton:pressed {
                background-color: #3249b5;
            }
            QTextEdit {
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                background-color: #ffffff;
            }
        """
