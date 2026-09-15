"""
Trinh soan thao G-code voi cot so dong, bao do loi/canh bao truc tiep tren tung dong,
va tu dong chen so thu tu dong (N).
"""

import re
from PyQt5.QtWidgets import QPlainTextEdit, QWidget, QTextEdit, QToolTip
from PyQt5.QtGui import (
    QTextCursor, QKeyEvent, QFont, QColor, QPainter,
    QTextCharFormat, QTextFormat
)
from PyQt5.QtCore import Qt, QRect, QSize, QEvent

_N_PREFIX_RE = re.compile(r"^\s*N(\d+)\s*")


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self):
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.code_editor.line_number_area_paint_event(event)

    def event(self, event):
        if event.type() == QEvent.ToolTip:
            block = self.code_editor.firstVisibleBlock()
            top = self.code_editor.blockBoundingGeometry(block).translated(self.code_editor.contentOffset()).top()
            bottom = top + self.code_editor.blockBoundingRect(block).height()
            y = event.pos().y()
            while block.isValid() and top <= y:
                if bottom >= y:
                    line_num = block.blockNumber() + 1
                    if line_num in self.code_editor._error_lines:
                        QToolTip.showText(event.globalPos(), f"⚠ {self.code_editor._error_lines[line_num]}", self)
                        return True
                    break
                block = block.next()
                top = bottom
                bottom = top + self.code_editor.blockBoundingRect(block).height()
            QToolTip.hideText()
        return super().event(event)


class GcodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.auto_number_enabled = True
        self.auto_number_step = 1
        self.auto_number_width = 0  # >0: dem so 0 phia truoc, vd width=3 -> N005

        self._error_lines = {}       # {line_num: message_str}
        self._sim_line = -1          # dong dang mo phong (xanh)
        self._is_dark_mode = False

        # Cot so thu tu dong (Line Number Area)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.update_line_number_area_width(0)

    def line_number_area_width(self):
        digits = 1
        m = max(1, self.blockCount())
        while m >= 10:
            m //= 10
            digits += 1
        char_w = self.fontMetrics().horizontalAdvance('9') if hasattr(self.fontMetrics(), 'horizontalAdvance') else self.fontMetrics().width('9')
        space = 22 + char_w * max(2, digits) + 8
        return space

    def update_line_number_area_width(self, _=0):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self.line_number_area)

        bg_color = QColor("#222222") if self._is_dark_mode else QColor("#f1f5f9")
        painter.fillRect(event.rect(), bg_color)

        # Duong ke chia cach giua cot so dong va vung soan thao
        border_color = QColor("#444444") if self._is_dark_mode else QColor("#cbd5e1")
        painter.setPen(border_color)
        x_border = self.line_number_area.width() - 1
        painter.drawLine(x_border, event.rect().top(), x_border, event.rect().bottom())

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        f_height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_num = block_number + 1
                has_error = line_num in self._error_lines
                is_sim = (line_num == self._sim_line)

                painter.setFont(self.font())

                if has_error:
                    # Icon canh bao do ben trai
                    painter.setPen(QColor("#ef4444"))
                    badge_rect = QRect(2, int(top), 16, int(f_height))
                    painter.drawText(badge_rect, Qt.AlignCenter, "⚠")
                    # So dong mau do
                    painter.setPen(QColor("#ef4444"))
                elif is_sim:
                    # So dong dang chay mo phong: mau xanh
                    painter.setPen(QColor("#10b981"))
                else:
                    painter.setPen(QColor("#71717a") if self._is_dark_mode else QColor("#94a3b8"))

                w = self.line_number_area.width() - 24
                text_rect = QRect(18, int(top), max(10, w), int(f_height))
                painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, str(line_num))

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            block_number += 1

    def set_error_lines(self, errors: dict):
        """Cap nhat danh sach dong co loi/canh bao: {line_num: message_str}."""
        self._error_lines = dict(errors)
        self._refresh_selections()
        self.line_number_area.update()

    def set_simulation_line(self, line_num: int):
        """Danh dau dong dang duoc mo phong (to mau xanh). line_num <= 0 de tat."""
        self._sim_line = line_num if line_num > 0 else -1
        self._refresh_selections()
        self.line_number_area.update()
        if self._sim_line > 0:
            block = self.document().findBlockByNumber(self._sim_line - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()

    def set_dark_mode(self, dark: bool):
        self._is_dark_mode = dark
        self._refresh_selections()
        self.line_number_area.update()

    def _refresh_selections(self):
        """To mau highlight cho cac dong loi (do) va dong mo phong (xanh)."""
        extra_selections = []

        # 1. Cac dong bi loi / canh bao: to do toan dong + gach chan luon song do
        for line_num, msg in self._error_lines.items():
            block = self.document().findBlockByNumber(line_num - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.format.setProperty(QTextFormat.FullWidthSelection, True)
                if self._is_dark_mode:
                    sel.format.setBackground(QColor(185, 28, 28, 70))
                    sel.format.setUnderlineColor(QColor("#ef4444"))
                    sel.format.setUnderlineStyle(QTextCharFormat.WaveUnderline)
                else:
                    sel.format.setBackground(QColor(254, 226, 226, 180))
                    sel.format.setUnderlineColor(QColor("#dc2626"))
                    sel.format.setUnderlineStyle(QTextCharFormat.WaveUnderline)
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                sel.cursor = cursor
                extra_selections.append(sel)

        # 2. Dong dang mo phong: to xanh la
        if self._sim_line > 0:
            block = self.document().findBlockByNumber(self._sim_line - 1)
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.format.setProperty(QTextFormat.FullWidthSelection, True)
                if self._is_dark_mode:
                    sel.format.setBackground(QColor(16, 185, 129, 90))
                else:
                    sel.format.setBackground(QColor(220, 252, 231, 200))
                cursor = QTextCursor(block)
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                sel.cursor = cursor
                extra_selections.append(sel)

        self.setExtraSelections(extra_selections)

    def viewportEvent(self, event):
        """Hien thi tooltip giai thich loi khi re chuot qua dong bi loi trong editor."""
        if event.type() == QEvent.ToolTip:
            cursor = self.cursorForPosition(event.pos())
            line_num = cursor.blockNumber() + 1
            if line_num in self._error_lines:
                QToolTip.showText(event.globalPos(), f"⚠ {self._error_lines[line_num]}", self.viewport())
                return True
            else:
                QToolTip.hideText()
        return super().viewportEvent(event)

    def event(self, event):
        """Hien thi tooltip giai thich loi khi re chuot qua dong bi loi."""
        if event.type() == QEvent.ToolTip:
            cursor = self.cursorForPosition(event.pos())
            line_num = cursor.blockNumber() + 1
            if line_num in self._error_lines:
                QToolTip.showText(event.globalPos(), f"⚠ {self._error_lines[line_num]}", self)
                return True
            else:
                QToolTip.hideText()
        return super().event(event)

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
            if cursor.block().text() == "":
                cursor.insertText(self._format_n(next_n) + " ")
                self.setTextCursor(cursor)
            return
        super().keyPressEvent(event)

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
            self.update_line_number_area_width(0)
            event.accept()
            return
        super().wheelEvent(event)
