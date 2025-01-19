@echo off
pyside6-uic ui/MainWindow.ui -o ui/MainWindow.py
pyside6-rcc ui\MainWindow.qrc -o MainWindow_rc.py