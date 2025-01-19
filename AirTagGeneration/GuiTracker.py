import sys
import folium
from PySide6 import QtWidgets, QtWebEngineWidgets

from ui.MainWindow import Ui_MainWindow


# TODO add UI for changing these parameters
HOURS = 24  # only show reports not older than these hours
PREFIX = ""  # only use keyfiles starting with this prefix
REGEN = "store_true"  # regenerate search-party-token
TRUSTEDDEVICE = "store_true"  # use trusted device for 2FA instead of SMS


class FindMyFlipperUi(QtWidgets.QMainWindow):
    def __init__(self):
        super(FindMyFlipperUi, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.showMaximized()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    widget = FindMyFlipperUi()
    sys.exit(app.exec())
