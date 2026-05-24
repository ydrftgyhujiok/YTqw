"""AI Short Video Clip Generator — точка входа."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from src.gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AI Short Video Clip Generator")
    app.setOrganizationName("ai-clip-gen")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
