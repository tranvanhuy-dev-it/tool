"""
Kiem tra license MOI LAN UNG DUNG KHOI DONG - CHI ap dung cho ban DA DONG
GOI (.exe qua PyInstaller), KHONG ap dung khi chay truc tiep tu source code
(python3 run.py luc dev/test) - phat hien qua sys.frozen (PyInstaller tu
dat thuoc tinh nay, source code thuong khong co).

Co che: installer.iss (buoc cai dat) da GOI SERVER 1 LAN DUY NHAT luc cai
dat (qua /api/verify) de xac minh ma + gan voi Machine GUID cua may, roi
luu ca 2 vao file "license.token" CANH file .exe. Sau do, MOI LAN APP
KHOI DONG chi SO SANH CUC BO: doc lai Machine GUID da luu trong token, so
voi Machine GUID HIEN TAI cua may - KHONG goi lai server nua (nhanh hon,
khong phu thuoc mang luc mo app). Neu file .exe (kem token) bi COPY sang
may khac, Machine GUID se khac va app tu choi chay.

Danh doi da chap nhan: neu ai do biet duoc Machine GUID that cua 1 may da
kich hoat va TU SUA file token tren may khac de khop, ho co the vuot qua
kiem tra nay (khong con server nao doi chieu lai) - chap nhan rui ro nay
o muc do thap de doi lay UX nhanh/khong can mang luc mo app.

Khong dung AI/ML - chi la so sanh chuoi doc tu file va registry.
"""

import os
import sys

# winreg CHI co tren Windows - import co dieu kien de module nay VAN import
# duoc binh thuong tren Linux/macOS luc dev (dung sys.frozen de biet co can
# dung winreg hay khong truoc khi goi, xem _get_machine_id()).
try:
    import winreg
except ImportError:
    winreg = None

TOKEN_FILENAME = "license.token"


def is_frozen_build() -> bool:
    """True neu dang chay tu ban DA DONG GOI (.exe qua PyInstaller), False
    neu dang chay truc tiep tu source code (python3 run.py)."""
    return getattr(sys, "frozen", False)


def _app_dir() -> str:
    """Thu muc chua file .exe (khi da dong goi) - noi installer.iss da luu
    file license.token vao cung."""
    if is_frozen_build():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_machine_id() -> str:
    """Doc Machine GUID cua Windows (HKLM\\SOFTWARE\\Microsoft\\Cryptography)
    - CUNG 1 gia tri ma installer.iss da doc va gui len server luc kich
    hoat, nen phai dung DUNG registry key do de so sanh khop."""
    if winreg is None:
        return ""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
        )
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return value
    except OSError:
        return ""


def _read_token_file() -> tuple:
    """Doc file license.token da duoc installer.iss luu lai luc kich hoat -
    tra ve (code, machine_id_tu_file) hoac (None, None) neu khong doc duoc."""
    path = os.path.join(_app_dir(), TOKEN_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) < 2:
            return None, None
        return lines[0].strip(), lines[1].strip()
    except OSError:
        return None, None


def verify_license_or_exit():
    """Kiem tra license neu dang chay ban DA DONG GOI - neu khong hop le,
    hien thong bao loi va THOAT UNG DUNG NGAY (khong cho vao giao dien
    chinh). Khong lam gi ca (return ngay) neu dang chay tu source code.
    CHI SO SANH CUC BO (token da luu vs Machine GUID hien tai), KHONG goi
    server - xem docstring dau file ve danh doi da chap nhan."""
    if not is_frozen_build():
        return

    code, saved_machine_id = _read_token_file()
    if not code or not saved_machine_id:
        _show_error_and_exit(
            "Không tìm thấy thông tin bản quyền hợp lệ.\n"
            "Vui lòng cài đặt lại ứng dụng bằng bộ cài đặt chính thức."
        )
        return

    current_machine_id = _get_machine_id()
    if not current_machine_id or current_machine_id != saved_machine_id:
        _show_error_and_exit(
            "Ứng dụng này đã được cài đặt trên một máy khác.\n"
            "Vui lòng cài đặt lại bằng bộ cài đặt chính thức trên máy này."
        )


def _show_error_and_exit(message: str):
    """Hien hop thoai loi bang chinh Qt (khong dung tkinter/console rieng,
    de dong nhat giao dien voi phan con lai cua app) roi thoat ung dung."""
    from PyQt5.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication(sys.argv)

    QMessageBox.critical(None, "Lỗi bản quyền", message)
    sys.exit(1)
