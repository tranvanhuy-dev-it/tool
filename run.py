"""Diem khoi chay GCode Vision. Chay: python3 run.py"""

import os
import sys


# Tren Linux (dac biet la Ubuntu GNOME Wayland), PyQt5 hoat dong on dinh nhat
# va maximize chuan xac 100% thong qua lop tuong thich XWayland (xcb).
# Plugin native 'wayland' cua Qt 5.15 thieu giao thuc trang tri cua so va
# khong the maximize tren Mutter/GNOME, khien cua so bi thu nho va lech ty le.
# Neu nguoi dung chua dat thu cong QT_QPA_PLATFORM tren Linux, uu tien dung 'xcb'.
if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from gcode_vision.main_window import main

if __name__ == "__main__":
    main()
