"""
Trinh soan thao G-code voi tinh nang tu dong chen so thu tu dong (N).

Khi nguoi dung nhan Enter de xuong dong moi, editor tu dong chen
"N<so>" o dau dong moi (vd N0, N10, N20... tuy buoc nhay cau hinh),
giong quy uoc danh so dong pho bien trong chuong trinh CNC.
"""

import re
from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtGui import QTextCursor, QKeyEvent, QFont
from PyQt5.QtCore import Qt

_N_PREFIX_RE = re.compile(r"^\s*N(\d+)\s*")


class GcodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.auto_number_enabled = True
        self.auto_number_step = 1
        self.auto_number_width = 0  # >0: dem so 0 phia truoc, vd width=3 -> N005

    def set_auto_number(self, enabled: bool, step: int = None, width: int = None):
        self.auto_number_enabled = enabled
        if step is not None:
            self.auto_number_step = max(1, step)
        if width is not None:
            self.auto_number_width = max(0, width)

    def _format_n(self, value: int) -> str:
        if self.auto_number_width > 0:
            return f"N{value:0{self.auto_number_width}d}"
        return f"N{value}"

    def _last_line_n_value(self) -> int:
        """Tim gia tri N cua dong GAN NHAT (khong tinh dong dang go do) co chua N,
        de tinh dong tiep theo = do + buoc nhay. Neu chua co dong nao co N, tra ve
        -step de dong dau tien ra dung 0 (hoac gia tri bat dau)."""
        doc_text_before_cursor = self.textCursor()
        block = doc_text_before_cursor.block().previous()
        while block.isValid():
            m = _N_PREFIX_RE.match(block.text())
            if m:
                return int(m.group(1))
            block = block.previous()
        return -self.auto_number_step

    def keyPressEvent(self, event: QKeyEvent):
        if (self.auto_number_enabled and
                event.key() in (Qt.Key_Return, Qt.Key_Enter) and
                not (event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier))):
            super().keyPressEvent(event)
            next_n = self._last_line_n_value() + self.auto_number_step
            cursor = self.textCursor()
            # chi chen N neu dong hien tai (vua tao) dang rong - tranh chen chong
            # len noi dung nguoi dung paste nhieu dong hoac go nhanh.
            if cursor.block().text() == "":
                cursor.insertText(self._format_n(next_n) + " ")
                self.setTextCursor(cursor)
            return
        super().keyPressEvent(event)

    # Ctrl + cuon chuot trong vung soan thao: phong to/thu nho co chu, giong hau
    # het code editor chuyen nghiep (VSCode, Notepad++...), khong doi cuon thuong.
    MIN_FONT_PT = 6
    MAX_FONT_PT = 48

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            font = self.font()
            new_size = font.pointSize() + (1 if delta > 0 else -1)
            new_size = max(self.MIN_FONT_PT, min(self.MAX_FONT_PT, new_size))
            font.setPointSize(new_size)
            self.setFont(font)
            event.accept()
            return
        super().wheelEvent(event)
