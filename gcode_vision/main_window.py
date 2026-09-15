"""
Cua so chinh: ghep trinh soan thao G-code (trai) va canvas xem truoc (phai).

Giao dien BASIC: dung widget Qt mac dinh, khong custom stylesheet/theme/icon -
chi bo cuc cac nut va o nhap can thiet, de doc va de bao tri.

Luong hoat dong:
  1. Nguoi dung go G-code vao editor (dinh dang .txt chuan de nap may CNC).
  2. Moi khi noi dung thay doi -> parse lai toan bo -> ve lai canvas.
  3. Nguoi dung click chuot vao canvas tai mot vi tri bat ky:
       - He TUYET DOI (G90): chen "X.. Y.." la toa do thuc te tai diem click.
       - He TUONG DOI (G91): chen "X.. Y.." la do lech so voi diem click TRUOC DO
         (hoac so voi vi tri dao hien tai neu chua co lan click nao).
     Chuoi toa do duoc chen dung vao VI TRI CON TRO trong editor, tu them dau
     cach neu ky tu truoc do dinh lien.
  4. Chuot phai tren canvas = hoan tac. Ctrl+keo = di chuyen (pan). Cuon = zoom
     quanh vi tri con tro. Diem giao luoi gan chuot duoc "hut" (snap) khi click.
"""

import math
import os
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPlainTextEdit, QLabel, QRadioButton, QButtonGroup, QPushButton,
    QFileDialog, QStatusBar, QSplitter, QMessageBox, QSlider, QDoubleSpinBox,
    QSpinBox, QCheckBox, QColorDialog, QGridLayout
)
from PyQt5.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QIcon, QKeySequence
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QShortcut, QTableWidget, QTableWidgetItem, QAbstractItemView
import re
import datetime
import shutil

from gcode_vision.gcode_parser import parse_gcode, convert_gcode_mode, estimate_machining_time_seconds
from gcode_vision.canvas_widget import CanvasWidget
from gcode_vision.gcode_editor import GcodeEditor
from gcode_vision.ruler_dialog import RulerWidget, RULER_THICKNESS


class GcodeHighlighter(QSyntaxHighlighter):
    """To mau co ban cho G-code bang regex (khong dung AI)."""

    def __init__(self, document):
        super().__init__(document)
        self.fmt_g = QTextCharFormat()
        self.fmt_g.setForeground(QColor("#0057d8"))
        self.fmt_g.setFontWeight(QFont.Bold)

        self.fmt_coord = QTextCharFormat()
        self.fmt_coord.setForeground(QColor("#0a7d3a"))

        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor("#888888"))
        self.fmt_comment.setFontItalic(True)

    def highlightBlock(self, text):
        for m in re.finditer(r"\bG\d+\b|\bM\d+\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_g)
        for m in re.finditer(r"\b[XYZIJF]-?\d+\.?\d*\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_coord)
        for m in re.finditer(r";.*$|\([^)]*\)", text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_comment)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GCode Vision")
        logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))
        self.resize(1400, 850)

        self.absolute_mode = True   # True = G90, False = G91
        self.last_ref_point = (0.0, 0.0)  # diem tham chieu cho che do tuong doi
        self._base_app_font_pt = QApplication.font().pointSize()
        self.ui_scale_pct = 100
        self._ruler_calib_x = None  # (pixel_positions, mm_positions) neu da hieu chuan thuoc chi tiet
        self._ruler_calib_y = None
        self._measure_first_point = None  # diem dau tien da click cua cong cu do khoang cach tam thoi
        self._render_debounce_timer = QTimer(self)
        self._render_debounce_timer.setSingleShot(True)
        self._render_debounce_timer.timeout.connect(self._render)

        self._current_file_path = None  # duong dan file dang mo, None neu chua tung luu/mo
        self._dirty = False  # co thay doi CHUA duoc luu ke tu lan luu/mo gan nhat

        self._build_ui()
        self._connect_signals()
        self._refresh_color_swatches()
        self.btn_dark_mode.setChecked(True)  # mac dinh mo che do toi
        self._render()

        self._setup_autosave()
        self._offer_restore_autosave()
        self._setup_shortcuts()
        self._update_window_title()

    # ---------------- UI ----------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- 2 hang can doi, chiem het chieu ngang ---
        # hang 1: Tep + He toa do khi click
        row1 = QHBoxLayout()
        row1.setSpacing(16)

        grp_file, l = self._section("Tệp")
        self.btn_new = QPushButton("Tạo mới")
        self.btn_open = QPushButton("Mở G-code")
        self.btn_save = QPushButton("Xuất G-code (.txt)")
        self.btn_undo = QPushButton("Hoàn tác")
        l.addWidget(self.btn_new)
        l.addWidget(self.btn_open)
        l.addWidget(self.btn_save)
        l.addWidget(self.btn_undo)

        grp_coord, l = self._section("Hệ tọa độ khi click")
        self.radio_abs = QRadioButton("Tuyệt đối (G90)")
        self.radio_rel = QRadioButton("Tương đối (G91)")
        self.radio_abs.setChecked(True)
        coord_group = QButtonGroup(self)
        coord_group.addButton(self.radio_abs)
        coord_group.addButton(self.radio_rel)
        l.addWidget(self.radio_abs)
        l.addWidget(self.radio_rel)
        l.addWidget(QLabel("Số thập phân:"))
        self.spin_decimals = QSpinBox()
        self.spin_decimals.setRange(0, 6)
        self.spin_decimals.setValue(0)
        self.spin_decimals.setMinimumWidth(55)
        l.addWidget(self.spin_decimals)
        self.chk_snap = QCheckBox("Hút lưới")
        self.chk_snap.setChecked(True)
        l.addWidget(self.chk_snap)
        l.addWidget(QLabel("Cỡ điểm giao (px):"))
        self.spin_marker_size = QSpinBox()
        self.spin_marker_size.setRange(2, 40)
        self.spin_marker_size.setValue(9)
        self.spin_marker_size.setMinimumWidth(55)
        l.addWidget(self.spin_marker_size)
        self.chk_measure_mode = QCheckBox("Đo khoảng cách (không chèn G-code)")
        l.addWidget(self.chk_measure_mode)
        self.chk_auto_n = QCheckBox("Tự đánh số N, bước:")
        self.chk_auto_n.setChecked(True)
        l.addWidget(self.chk_auto_n)
        self.spin_n_step = QSpinBox()
        self.spin_n_step.setRange(1, 1000)
        self.spin_n_step.setValue(1)
        self.spin_n_step.setMinimumWidth(55)
        l.addWidget(self.spin_n_step)
        row1.addWidget(grp_file)
        row1.addWidget(grp_coord)
        row1.addStretch()

        self.lbl_website = QLabel('<a href="https://www.tranvanhuy.io.vn">tranvanhuy.io.vn</a>')
        self.lbl_website.setOpenExternalLinks(True)
        row1.addWidget(self.lbl_website)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setMinimumWidth(32)
        row1.addWidget(self.btn_zoom_out)
        self.lbl_zoom_pct = QLabel("100%")
        self.lbl_zoom_pct.setMinimumWidth(44)
        self.lbl_zoom_pct.setAlignment(Qt.AlignCenter)
        row1.addWidget(self.lbl_zoom_pct)
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setMinimumWidth(32)
        row1.addWidget(self.btn_zoom_in)

        self.btn_dark_mode = QPushButton("Chế độ tối")
        self.btn_dark_mode.setCheckable(True)
        row1.addWidget(self.btn_dark_mode)
        root.addLayout(row1)

        # hang 2: Anh ban ve tham chieu, Mau net ve
        row2 = QHBoxLayout()
        row2.setSpacing(16)

        grp_img, l = self._section("Ảnh bản vẽ tham chiếu")
        self.btn_load_image = QPushButton("Tải ảnh...")
        l.addWidget(self.btn_load_image)
        l.addWidget(QLabel("Rộng phôi (mm):"))
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.01, 100000)
        self.spin_width.setDecimals(2)
        self.spin_width.setValue(100.0)
        self.spin_width.setMinimumWidth(85)
        l.addWidget(self.spin_width)
        l.addWidget(QLabel("Cao phôi (mm):"))
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(0.01, 100000)
        self.spin_height.setDecimals(2)
        self.spin_height.setValue(100.0)
        self.spin_height.setMinimumWidth(85)
        l.addWidget(self.spin_height)
        l.addWidget(QLabel("a (X):"))
        self.spin_ax = QDoubleSpinBox()
        self.spin_ax.setRange(-100000, 100000)
        self.spin_ax.setDecimals(3)
        self.spin_ax.setMinimumWidth(85)
        l.addWidget(self.spin_ax)
        l.addWidget(QLabel("a (Y):"))
        self.spin_ay = QDoubleSpinBox()
        self.spin_ay.setRange(-100000, 100000)
        self.spin_ay.setDecimals(3)
        self.spin_ay.setMinimumWidth(85)
        l.addWidget(self.spin_ay)
        l.addWidget(QLabel("Ô lưới (mm):"))
        self.spin_grid = QDoubleSpinBox()
        self.spin_grid.setRange(0.01, 10000)
        self.spin_grid.setDecimals(2)
        self.spin_grid.setValue(1.0)
        self.spin_grid.setMinimumWidth(75)
        l.addWidget(self.spin_grid)
        l.addWidget(QLabel("Độ mờ ảnh nền:"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.setValue(50)
        self.slider_opacity.setFixedWidth(100)
        l.addWidget(self.slider_opacity)
        row2.addWidget(grp_img)

        grp_colors, l = self._section("Màu nét vẽ")
        self._color_buttons = {}
        for key, label in (("cut", "Cắt"), ("rapid", "Chạy nhanh"),
                            ("grid", "Lưới"), ("axis", "Trục")):
            l.addWidget(QLabel(label))
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.clicked.connect(lambda _, k=key: self._pick_color(k))
            self._color_buttons[key] = btn
            l.addWidget(btn)
        row2.addWidget(grp_colors)
        row2.addStretch()

        root.addLayout(row2)

        # --- vung chinh: splitter 2 cot ---
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, stretch=1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Chương trình G-code (.txt)"))

        self.editor = GcodeEditor()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlaceholderText("G90\nG0 X0 Y0\nG1 X50 Y0\nG1 X50 Y30\n...")
        self.highlighter = GcodeHighlighter(self.editor.document())

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self.editor)

        points_panel = QWidget()
        points_layout = QVBoxLayout(points_panel)
        points_layout.setContentsMargins(0, 0, 0, 0)
        points_layout.addWidget(QLabel("Danh sách điểm X/Y trong chương trình"))
        self.table_points = QTableWidget(0, 3)
        self.table_points.setHorizontalHeaderLabels(["Dòng", "X (mm)", "Y (mm)"])
        self.table_points.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_points.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_points.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_points.verticalHeader().setVisible(False)
        points_layout.addWidget(self.table_points)
        left_splitter.addWidget(points_panel)
        left_splitter.setSizes([600, 200])

        left_layout.addWidget(left_splitter)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_header = QHBoxLayout()
        right_header.addWidget(QLabel("Xem trước đường chạy dao"))

        self.lbl_mouse_coord = QLabel("X —   Y —")
        coord_font = QFont("Consolas", 12)
        coord_font.setBold(True)
        self.lbl_mouse_coord.setFont(coord_font)
        right_header.addWidget(self.lbl_mouse_coord)
        right_header.addStretch()

        right_layout.addLayout(right_header)

        # Thuoc do THUONG TRUC (giong Word): luoi 2x2 quanh canvas - goc trong,
        # thuoc X (ngang) o tren, thuoc Y (doc) o trai, canvas o giua. Luon
        # hien san, khong can bam nut de bat/tat; dong bo qua view_changed.
        canvas_grid = QWidget()
        grid = QGridLayout(canvas_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        self.canvas = CanvasWidget()
        self.ruler_x = RulerWidget("x", self.canvas)
        self.ruler_y = RulerWidget("y", self.canvas)
        corner = QWidget()
        corner.setFixedSize(RULER_THICKNESS, RULER_THICKNESS)

        grid.addWidget(corner, 0, 0)
        grid.addWidget(self.ruler_x, 0, 1)
        grid.addWidget(self.ruler_y, 1, 0)
        grid.addWidget(self.canvas, 1, 1)

        right_layout.addWidget(canvas_grid)
        splitter.addWidget(right)

        splitter.setSizes([420, 980])

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Sẵn sàng.")

    @staticmethod
    def _section(title: str):
        """Mot 'nhom' don gian: chi tieu de + hang ngang chua control, khong co
        khung vien QGroupBox bao quanh. Tra ve (widget_container, inner_hlayout)."""
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addWidget(QLabel(title))
        inner = QHBoxLayout()
        inner.setSpacing(14)
        outer.addLayout(inner)
        return container, inner

    def _connect_signals(self):
        self.editor.textChanged.connect(self._schedule_render)
        self.editor.textChanged.connect(self._mark_dirty)
        self.canvas.point_clicked.connect(self._on_canvas_clicked)
        self.chk_measure_mode.toggled.connect(self._on_measure_mode_toggled)
        self.table_points.itemSelectionChanged.connect(self._on_point_row_selected)
        self.canvas.undo_requested.connect(self._on_canvas_undo)
        self.canvas.mouse_moved_mm.connect(self._on_canvas_mouse_moved)
        self.chk_snap.toggled.connect(self.canvas.set_snap_enabled)
        self.spin_marker_size.valueChanged.connect(self.canvas.set_marker_radius)
        self.chk_auto_n.toggled.connect(
            lambda v: self.editor.set_auto_number(v, self.spin_n_step.value()))
        self.spin_n_step.valueChanged.connect(
            lambda v: self.editor.set_auto_number(self.chk_auto_n.isChecked(), v))
        self.radio_abs.toggled.connect(self._on_mode_toggled)
        self.btn_new.clicked.connect(self._new_file)
        self.btn_open.clicked.connect(self._open_file)
        self.btn_save.clicked.connect(self._save_file)
        self.btn_undo.clicked.connect(self._on_canvas_undo)

        self.btn_load_image.clicked.connect(self._load_drawing_image)
        self.ruler_x.calibration_changed.connect(self._on_ruler_calibration_changed)
        self.ruler_y.calibration_changed.connect(self._on_ruler_calibration_changed)
        self.spin_width.valueChanged.connect(self._on_image_params_changed)
        self.spin_height.valueChanged.connect(self._on_image_params_changed)
        self.spin_ax.valueChanged.connect(self._on_image_params_changed)
        self.spin_ay.valueChanged.connect(self._on_image_params_changed)
        self.spin_grid.valueChanged.connect(self._on_image_params_changed)
        self.slider_opacity.valueChanged.connect(
            lambda v: (self.canvas.set_background_opacity(v / 100.0), self._render())
        )
        self.btn_dark_mode.toggled.connect(self._toggle_dark_mode)
        self.btn_zoom_in.clicked.connect(lambda: self._change_ui_scale(10))
        self.btn_zoom_out.clicked.connect(lambda: self._change_ui_scale(-10))

    # ---------------- logic ----------------

    def _change_ui_scale(self, delta_pct: int):
        """Phong to/thu nho toan bo giao dien bang cach nhan he so len co chu mac
        dinh. QApplication.setFont() chi anh huong widget se duoc tao SAU do, nen
        phai tu duyet va set lai font cho tat ca widget DANG CO SAN trong cua so
        (tru vung soan thao G-code, vi no co Ctrl+cuon rieng de nguoi dung tu chinh
        co chu doc lap voi UI scale nay)."""
        new_pct = max(60, min(200, self.ui_scale_pct + delta_pct))
        if new_pct == self.ui_scale_pct:
            return
        self.ui_scale_pct = new_pct

        new_size = self._base_app_font_pt * new_pct / 100.0
        app_font = QApplication.font()
        app_font.setPointSizeF(new_size)
        QApplication.setFont(app_font)

        for widget in self.findChildren(QWidget):
            if widget is self.editor:
                continue
            f = widget.font()
            f.setPointSizeF(new_size)
            widget.setFont(f)

        self.lbl_zoom_pct.setText(f"{new_pct}%")

    def _toggle_dark_mode(self, dark: bool):
        """Bat/tat che do toi: doi mau nen/chu toan bo giao dien bang 1 stylesheet
        don gian, khong anh huong bo cuc/spacing da co san."""
        if dark:
            self.setStyleSheet("""
                QWidget { background-color: #2b2b2b; color: #e0e0e0; }
                QPlainTextEdit { background-color: #1e1e1e; color: #dcdcdc; }
                QPushButton { background-color: #3c3c3c; border: 1px solid #555; padding: 6px 12px; }
                QPushButton:hover { background-color: #4a4a4a; }
                QPushButton:checked { background-color: #0a5a9c; }
                QDoubleSpinBox, QSpinBox { background-color: #1e1e1e; color: #dcdcdc; border: 1px solid #555; padding: 2px 4px; }
            """)
            self.btn_dark_mode.setText("Chế độ sáng")
            link_color = "#6ab0f3"
        else:
            self.setStyleSheet("")
            self.btn_dark_mode.setText("Chế độ tối")
            link_color = "#0b5fbf"

        # QLabel voi the <a> dung mau lien ket rieng cua Qt (khong theo CSS "color"
        # chung), nen phai chen mau truc tiep vao HTML de doc duoc tren ca 2 nen.
        self.lbl_website.setText(
            f'<a href="https://www.tranvanhuy.io.vn" style="color:{link_color};">tranvanhuy.io.vn</a>'
        )

        # Ep Qt tinh lai kich thuoc cac nut theo padding moi cua stylesheet - neu
        # khong, nut giu nguyen sizeHint cu (tu luc khoi tao) va chu bi cat/tran.
        for btn in self.findChildren(QPushButton):
            btn.updateGeometry()

    def _on_mode_toggled(self, checked):
        new_absolute = self.radio_abs.isChecked()
        if new_absolute == self.absolute_mode:
            return
        old_text = self.editor.toPlainText()
        nd = self.spin_decimals.value()
        converted = convert_gcode_mode(old_text, to_absolute=new_absolute, decimals=nd)
        converted = self._ensure_leading_mode_line(converted, new_absolute)
        self.absolute_mode = new_absolute
        self.editor.setPlainText(converted)
        self.status.showMessage(
            f"Đã chuyển sang chế độ {'tuyệt đối (G90)' if new_absolute else 'tương đối (G91)'} "
            f"— toạ độ trong chương trình đã được tính lại tương ứng."
        )

    @staticmethod
    def _ensure_leading_mode_line(text: str, absolute_mode: bool) -> str:
        """Dam bao dong DAU TIEN (khong tinh dong trong/comment) cua text la
        DUNG G90 hoac G91 tuong ung absolute_mode - thay the neu da co dong
        G90/G91 o dau, hoac chen moi neu chua co."""
        mode_line = "G90" if absolute_mode else "G91"
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.upper() in ("G90", "G91"):
                lines[i] = mode_line
            else:
                lines.insert(i, mode_line)
            return "\n".join(lines) + "\n"
        return mode_line + "\n"

    def _schedule_render(self):
        """Debounce viec render lai canvas: doi mot khoang ngan sau lan go phim
        CUOI CUNG roi moi parse+ve lai, thay vi lam viec do dong bo NGAY moi
        keystroke - voi chuong trinh G-code dai (hang nghin dong), render dong
        bo moi phim se lam UI thread bi chan lien tuc, cam giac nhu "treo"."""
        self._render_debounce_timer.start(150)

    def _render(self):
        text = self.editor.toPlainText()
        try:
            result = parse_gcode(text)
        except Exception as e:
            self.status.showMessage(f"Lỗi phân tích G-code: {e}")
            return
        self.canvas.render_program(result)
        self.last_ref_point = (result.end_x, result.end_y)
        nd = self.spin_decimals.value()
        self._refresh_points_table(result.segments, nd)

        time_str = self._format_machining_time(result.segments)
        msg = (
            f"{len(result.segments)} đoạn di chuyển | Vị trí dao hiện tại: "
            f"X{result.end_x:.{nd}f} Y{result.end_y:.{nd}f} | Ước tính thời gian: {time_str}"
        )
        if result.warnings:
            msg += f"  ⚠ {result.warnings[0]}"
        self.status.showMessage(msg)

    def _refresh_points_table(self, segments, nd: int):
        """Cap nhat bang danh sach diem: MOI dong ung voi 1 doan di chuyen
        (segment) trong G-code, hien so dong nguon + toa do DICH (x1,y1) -
        click vao 1 dong se dua con tro editor toi dong G-code tuong ung va
        highlight diem do tren canvas, giup tra cuu/sua nhanh tung diem ma
        khong phai doc thu cong toan bo van ban."""
        self.table_points.blockSignals(True)
        self.table_points.setRowCount(len(segments))
        for row, seg in enumerate(segments):
            item_line = QTableWidgetItem(str(seg.source_line))
            item_x = QTableWidgetItem(f"{seg.x1:.{nd}f}")
            item_y = QTableWidgetItem(f"{seg.y1:.{nd}f}")
            for item in (item_line, item_x, item_y):
                item.setData(Qt.UserRole, (seg.source_line, seg.x1, seg.y1))
            self.table_points.setItem(row, 0, item_line)
            self.table_points.setItem(row, 1, item_x)
            self.table_points.setItem(row, 2, item_y)
        self.table_points.blockSignals(False)

    def _on_point_row_selected(self):
        rows = self.table_points.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        item = self.table_points.item(row, 0)
        if item is None:
            return
        source_line, x_mm, y_mm = item.data(Qt.UserRole)

        # dua con tro editor toi DUNG dong nguon cua diem nay
        if source_line >= 1:
            cursor = self.editor.textCursor()
            block = self.editor.document().findBlockByNumber(source_line - 1)
            if block.isValid():
                cursor.setPosition(block.position())
                cursor.movePosition(cursor.EndOfBlock, cursor.KeepAnchor)
                self.editor.setTextCursor(cursor)
                self.editor.setFocus()

        # highlight diem tren canvas bang chinh co che do khoang cach (mot
        # dau cham don, khong ve doan noi) - tai dung 1 diem thi khong can
        # ve doan, chi can hien 1 marker de nguoi dung thay ro vi tri.
        self.canvas.show_measure_line(x_mm, y_mm, x_mm, y_mm)

    @staticmethod
    def _format_machining_time(segments) -> str:
        seconds = estimate_machining_time_seconds(segments)
        if seconds < 60:
            return f"{seconds:.0f} giây"
        minutes = seconds / 60.0
        if minutes < 60:
            return f"{minutes:.1f} phút"
        hours = minutes / 60.0
        return f"{hours:.1f} giờ"

    # ---------------- luu tru an toan (auto-save, khoi phuc, phim tat) ----------------

    _AUTOSAVE_DIR = os.path.join(os.path.expanduser("~"), ".gcode_vision")
    _AUTOSAVE_PATH = os.path.join(_AUTOSAVE_DIR, "autosave.txt")

    def _mark_dirty(self):
        self._dirty = True
        self._update_window_title()

    def _mark_clean(self):
        self._dirty = False
        self._update_window_title()

    def _update_window_title(self):
        name = os.path.basename(self._current_file_path) if self._current_file_path else "Chưa lưu"
        star = " *" if self._dirty else ""
        self.setWindowTitle(f"GCode Vision — {name}{star}")

    def _setup_autosave(self):
        """Tu dong luu 1 ban nhap (KHAC voi file that nguoi dung dang luu) moi
        30 giay NEU co thay doi chua luu - de khoi phuc duoc neu app bi dong
        dot ngot (crash, mat dien, lo tay tat may) ma chua kip Ctrl+S."""
        try:
            os.makedirs(self._AUTOSAVE_DIR, exist_ok=True)
        except Exception:
            return  # khong tao duoc thu muc (vd quyen truy cap) - bo qua auto-save, khong chan app
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._autosave_timer.start(30_000)

    def _do_autosave(self):
        if not self._dirty:
            return
        try:
            with open(self._AUTOSAVE_PATH, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
        except Exception:
            pass  # auto-save la tien ich phu, khong lam gian doan cong viec neu loi

    def _offer_restore_autosave(self):
        """Luc khoi dong, neu phat hien file auto-save con ton tai (tu lan
        chay truoc bi dong dot ngot), hoi nguoi dung co muon khoi phuc khong."""
        if not os.path.exists(self._AUTOSAVE_PATH):
            return
        try:
            with open(self._AUTOSAVE_PATH, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return
        if not content.strip():
            return
        reply = QMessageBox.question(
            self, "Khôi phục bản nháp",
            "Phát hiện một bản nháp chưa lưu từ lần chạy trước (có thể do ứng dụng "
            "bị đóng đột ngột). Bạn có muốn khôi phục lại nội dung đó không?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self.editor.setPlainText(content)
            self.status.showMessage("Đã khôi phục bản nháp từ lần chạy trước.")
        else:
            try:
                os.remove(self._AUTOSAVE_PATH)
            except Exception:
                pass

    def _clear_autosave(self):
        try:
            if os.path.exists(self._AUTOSAVE_PATH):
                os.remove(self._AUTOSAVE_PATH)
        except Exception:
            pass

    def _setup_shortcuts(self):
        """Phim tat chuan cho ung dung ky thuat: Ctrl+S luu, Ctrl+O mo,
        Ctrl+N tao moi - nguoi dung quen voi cac phan mem CAD/editor khac se
        dung duoc ngay khong can tim nut tren toolbar."""
        QShortcut(QKeySequence.Save, self).activated.connect(self._save_file)
        QShortcut(QKeySequence.Open, self).activated.connect(self._open_file)
        QShortcut(QKeySequence.New, self).activated.connect(self._new_file)

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(
                self, "Thoát ứng dụng",
                "Nội dung hiện tại chưa được lưu. Bạn có muốn lưu trước khi thoát?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save:
                if not self._save_file():
                    event.ignore()  # nguoi dung huy hop thoai luu -> khong thoat
                    return
        self._clear_autosave()
        event.accept()

    # ---------------- anh ban ve tham chieu ----------------
    #
    # Quy uoc: nguoi dung tu crop anh sao cho anh khop khit voi khung ngoai
    # cua phoi. Sau khi tai anh len, nhap Rong/Cao phoi (mm) va do lech a(X,Y)
    # tu goc duoi-trai anh den goc toa do gia cong that (0,0).

    def _load_drawing_image(self):
        start_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Tải ảnh bản vẽ", start_dir,
            "All files (*);;Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            self.canvas.set_background_image(path)
            self.canvas.set_background_opacity(self.slider_opacity.value() / 100.0)
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể tải ảnh: {e}")
            return

        img_w = self.canvas._bg_image_w_px
        img_h = self.canvas._bg_image_h_px
        if img_w > 0:
            suggested_height = self.spin_width.value() * (img_h / img_w)
            self.spin_height.blockSignals(True)
            self.spin_height.setValue(suggested_height)
            self.spin_height.blockSignals(False)

        self._on_image_params_changed()
        self._sync_rulers_to_canvas()
        self.status.showMessage(
            "Đã tải ảnh. Đã tự đặt Cao phôi theo đúng tỷ lệ khung hình. "
            "Kéo vạch trên thước (trên/trái canvas) hoặc double-click để thêm vạch chia "
            "nếu bản vẽ có vùng kích thước không đúng tỷ lệ đều."
        )

    def _sync_rulers_to_canvas(self):
        """Nap lai kich thuoc anh + calibration hien tai cua canvas vao 2
        thuoc do thuong truc - goi moi khi anh/hieu chuan thay doi tu nguon
        khac (tai anh moi, doi Rong/Cao phoi...) de thuoc luon dong bo."""
        img_w = self.canvas._bg_image_w_px
        img_h = self.canvas._bg_image_h_px
        self.ruler_x.set_image_size(img_w, img_h)
        self.ruler_y.set_image_size(img_w, img_h)
        self.ruler_x.load_calibration(
            self.canvas._calib_x.pixel_positions, self.canvas._calib_x.mm_positions)
        self.ruler_y.load_calibration(
            self.canvas._calib_y.pixel_positions, self.canvas._calib_y.mm_positions)

    def _on_ruler_calibration_changed(self, axis: str, pixel_positions: list, mm_positions: list):
        """Nguoi dung vua keo/nhap mm xong tren 1 thuoc - ap dung NGAY LAP TUC
        vao canvas (khong can nut Ap dung rieng). Anh nen GIU NGUYEN kich thuoc
        hien thi co dinh (khong co gian/meo theo tung lan sua mm - ty le trung
        binh thay doi lien tuc se rat kho nhin); CHI toa do khi click duoc tinh
        chinh xac theo tung doan calibration piecewise."""
        self.canvas.set_axis_calibration(axis, pixel_positions, mm_positions)
        if axis == "x":
            self._ruler_calib_x = (pixel_positions, mm_positions)
        else:
            self._ruler_calib_y = (pixel_positions, mm_positions)
        self._render()
        n_segs = len(pixel_positions) - 1
        self.status.showMessage(f"Đã cập nhật hiệu chỉnh thước đo trục {axis.upper()}: {n_segs} đoạn.")

    def _on_image_params_changed(self):
        self.canvas.set_workpiece_size(self.spin_width.value(), self.spin_height.value())
        self.canvas.set_offset_a(self.spin_ax.value(), self.spin_ay.value())
        self.canvas.set_grid_step(self.spin_grid.value())
        self._sync_rulers_to_canvas()
        self._render()

    def _is_within_workpiece(self, x_mm: float, y_mm: float) -> bool:
        """True neu (x_mm, y_mm) nam trong vung phoi da khai bao (goc (0,0) o
        goc DUOI-TRAI, theo dung quy uoc he toa do cua toan bo ung dung)."""
        w_mm = self.spin_width.value()
        h_mm = self.spin_height.value()
        eps = 1e-6
        return -eps <= x_mm <= w_mm + eps and -eps <= y_mm <= h_mm + eps

    def _on_measure_mode_toggled(self, checked: bool):
        self._measure_first_point = None
        self.canvas.clear_measure_line()
        if checked:
            self.status.showMessage("Chế độ đo khoảng cách: click 2 điểm liên tiếp trên bản vẽ.")

    def _on_canvas_clicked(self, x_mm: float, y_mm: float):
        if self.chk_measure_mode.isChecked():
            self._on_measure_click(x_mm, y_mm)
            return
        self._insert_coordinate(x_mm, y_mm)

    def _on_measure_click(self, x_mm: float, y_mm: float):
        """Cong cu do khoang cach/goc TAM THOI: click 2 diem lien tiep tren
        canvas de xem khoang cach va goc giua chung, KHONG chen bat ky gi vao
        G-code - chi de tham khao khi ve/can chinh. Click lan 3 se bat dau
        1 phep do MOI (diem vua click tro thanh diem dau tien)."""
        nd = self.spin_decimals.value()
        if self._measure_first_point is None:
            self._measure_first_point = (x_mm, y_mm)
            self.canvas.clear_measure_line()
            self.status.showMessage(
                f"Đo khoảng cách: điểm đầu X{x_mm:.{nd}f} Y{y_mm:.{nd}f} — "
                f"click điểm thứ hai để xem khoảng cách."
            )
            return

        x0, y0 = self._measure_first_point
        dx = x_mm - x0
        dy = y_mm - y0
        dist = (dx * dx + dy * dy) ** 0.5
        angle_deg = math.degrees(math.atan2(dy, dx))
        self.canvas.show_measure_line(x0, y0, x_mm, y_mm)
        self.status.showMessage(
            f"Khoảng cách: {dist:.{nd}f} mm   Góc: {angle_deg:.2f}°   "
            f"(ΔX={dx:.{nd}f}  ΔY={dy:.{nd}f}) — click để đo đoạn mới."
        )
        self._measure_first_point = None  # san sang cho phep do tiep theo

    def _insert_coordinate(self, x_mm: float, y_mm: float):
        """Chen toa do vao vi tri con tro hien tai trong editor."""
        nd = self.spin_decimals.value()
        if not self._is_within_workpiece(x_mm, y_mm):
            w_mm = self.spin_width.value()
            h_mm = self.spin_height.value()
            self.status.showMessage(
                f"Đã bỏ qua: X{x_mm:.{nd}f} Y{y_mm:.{nd}f} nằm ngoài kích thước phôi "
                f"({w_mm:g} × {h_mm:g} mm) — không chèn vào G-code."
            )
            return
        if self.absolute_mode:
            snippet = f"X{x_mm:.{nd}f} Y{y_mm:.{nd}f}"
        else:
            ref_x, ref_y = self.last_ref_point
            dx = x_mm - ref_x
            dy = y_mm - ref_y
            snippet = f"X{dx:.{nd}f} Y{dy:.{nd}f}"

        cursor = self.editor.textCursor()
        pos = cursor.position()
        if pos > 0:
            char_before = self.editor.toPlainText()[pos - 1]
            if char_before not in (" ", "\t", "\n"):
                snippet = " " + snippet
        cursor.insertText(snippet)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

        self.last_ref_point = (x_mm, y_mm)
        self.status.showMessage(
            f"Đã chèn: {snippet}  (click tại X{x_mm:.{nd}f} Y{y_mm:.{nd}f} tuyệt đối) — "
            f"chuột phải trên bản vẽ để hoàn tác"
        )

    def _on_canvas_undo(self):
        if self.chk_measure_mode.isChecked():
            self._measure_first_point = None
            self.canvas.clear_measure_line()
            self.status.showMessage("Đã huỷ phép đo đang chọn.")
            return
        self.editor.undo()
        self.status.showMessage("Đã hoàn tác thao tác gần nhất.")

    def _on_canvas_mouse_moved(self, x_mm: float, y_mm: float):
        nd = self.spin_decimals.value()
        self.lbl_mouse_coord.setText(f"X {x_mm:.{nd}f}   Y {y_mm:.{nd}f}")

    # ---------------- mau net ve ----------------

    def _pick_color(self, key: str):
        current = QColor(self.canvas.get_colors().get(key, "#000000"))
        color = QColorDialog.getColor(current, self, f"Chọn màu — {key}")
        if not color.isValid():
            return
        self.canvas.set_colors(**{key: color.name()})
        self._refresh_color_swatches()
        self._render()

    def _refresh_color_swatches(self):
        colors = self.canvas.get_colors()
        for key, btn in self._color_buttons.items():
            hexcol = colors.get(key, "#000000")
            btn.setStyleSheet(f"background-color: {hexcol};")

    # ---------------- file I/O ----------------

    def _new_file(self):
        if self.editor.toPlainText().strip():
            reply = QMessageBox.question(
                self, "Tạo mới",
                "Nội dung hiện tại chưa được lưu sẽ mất. Vẫn tạo chương trình mới?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        mode_line = "G90" if self.absolute_mode else "G91"
        self.editor.setPlainText(mode_line + "\n")
        self.last_ref_point = (0.0, 0.0)
        self._current_file_path = None
        self._mark_clean()
        self.status.showMessage("Đã tạo chương trình G-code mới.")

    def _open_file(self):
        start_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở chương trình G-code", start_dir,
            "All files (*);;Text files (*.txt *.nc *.gcode)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
            self._current_file_path = path
            self._mark_clean()
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể mở file: {e}")

    def _save_file(self) -> bool:
        """Luu chuong trinh G-code ra file, tra ve True neu luu THANH CONG
        (de closeEvent biet co the thoat duoc khong), False neu nguoi dung
        huy hop thoai hoac gap loi."""
        if not self._confirm_save_warnings():
            return False
        start_path = self._current_file_path or os.path.join(os.path.expanduser("~"), "program.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu chương trình G-code", start_path, "Text files (*.txt);;All files (*)")
        if not path:
            return False
        self._backup_previous_version(path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._build_export_text())
            self._current_file_path = path
            self._mark_clean()
            self.status.showMessage(f"Đã lưu: {path}")
            return True
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể lưu file: {e}")
            return False

    _VERSION_HISTORY_DIR_NAME = ".gcode_vision_history"

    def _backup_previous_version(self, path: str):
        """Truoc khi GHI DE 1 file DA TON TAI, sao chep ban CU sang thu muc
        lich su phien ban (canh file goc, dat theo timestamp) - de nguoi dung
        co the tim lai ban truoc do neu lo ghi de sai. Khong lam gi neu file
        chua ton tai (lan luu dau tien) hoac khong the sao chep (vd quyen)."""
        if not os.path.exists(path):
            return
        try:
            folder = os.path.join(os.path.dirname(path), self._VERSION_HISTORY_DIR_NAME)
            os.makedirs(folder, exist_ok=True)
            base = os.path.basename(path)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(folder, f"{base}.{stamp}.bak")
            shutil.copy2(path, backup_path)
            self._prune_old_versions(folder, base)
        except Exception:
            pass  # sao luu la tien ich phu, khong duoc chan viec luu file chinh

    _MAX_VERSIONS_PER_FILE = 20

    def _prune_old_versions(self, folder: str, base_name: str):
        """Chi giu lai toi da _MAX_VERSIONS_PER_FILE ban cu nhat cho MOI file
        (theo ten goc), xoa cac ban cu hon de thu muc lich su khong phinh to
        vo han qua thoi gian."""
        try:
            entries = [f for f in os.listdir(folder) if f.startswith(base_name + ".")]
            entries.sort()  # timestamp dang YYYYMMDD_HHMMSS nen sort chuoi = sort thoi gian
            excess = len(entries) - self._MAX_VERSIONS_PER_FILE
            for f in entries[:max(0, excess)]:
                os.remove(os.path.join(folder, f))
        except Exception:
            pass

    def _build_export_text(self) -> str:
        """Chen 1 khoi comment METADATA vao DAU noi dung xuat ra (ngay giu
        nguyen G-code - dong comment ";..." khong lam sai chuong trinh khi
        nap vao may CNC), ghi lai ngay gio xuat, kich thuoc phoi va offset -
        giup tra cuu lai boi canh cua file sau nay ma khong can nho lai."""
        nd = self.spin_decimals.value()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        w_mm = self.spin_width.value()
        h_mm = self.spin_height.value()
        ax = self.spin_ax.value()
        ay = self.spin_ay.value()
        mode = "G90 (tuyệt đối)" if self.absolute_mode else "G91 (tương đối)"
        header = (
            f"; Xuất bởi GCode Vision lúc {now}\n"
            f"; Kích thước phôi: {w_mm:g} x {h_mm:g} mm | Offset a(X,Y): {ax:g}, {ay:g}\n"
            f"; Chế độ tọa độ: {mode} | Số thập phân: {nd}\n"
        )
        return header + self.editor.toPlainText()

    def _confirm_save_warnings(self) -> bool:
        """Kiem tra chuong trinh G-code truoc khi luu, canh bao neu co toa do
        vuot ngoai kich thuoc phoi da khai bao hoac diem trung lap bat thuong
        (2 lenh chuyen dong lien tiep toi CUNG 1 toa do, thuong la do go nham).
        Tra ve True neu nguoi dung dong y luu tiep (hoac khong co canh bao
        nao), False neu nguoi dung chon huy de quay lai sua truoc."""
        try:
            result = parse_gcode(self.editor.toPlainText())
        except Exception:
            return True  # loi parse da duoc bao o status bar khi go, khong chan luu o day

        warnings = []
        w_mm = self.spin_width.value()
        h_mm = self.spin_height.value()
        out_of_bounds = 0
        for seg in result.segments:
            for x, y in ((seg.x0, seg.y0), (seg.x1, seg.y1)):
                if not self._is_within_workpiece(x, y):
                    out_of_bounds += 1
        if out_of_bounds:
            warnings.append(
                f"Có {out_of_bounds} điểm nằm ngoài kích thước phôi đã khai báo "
                f"({w_mm:g} × {h_mm:g} mm)."
            )

        duplicate = 0
        for seg in result.segments:
            if abs(seg.x0 - seg.x1) < 1e-6 and abs(seg.y0 - seg.y1) < 1e-6:
                duplicate += 1
        if duplicate:
            warnings.append(
                f"Có {duplicate} lệnh di chuyển tới đúng vị trí hiện tại "
                f"(không di chuyển) — có thể do gõ nhầm tọa độ."
            )

        if not warnings:
            return True

        text = "\n".join(f"• {w}" for w in warnings)
        reply = QMessageBox.warning(
            self, "Cảnh báo trước khi lưu",
            f"Phát hiện một số điểm bất thường trong chương trình:\n\n{text}\n\n"
            f"Vẫn muốn lưu file?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return reply == QMessageBox.Yes


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.showMaximized()
    # Tren mot so window manager Linux (vd lop tuong thich X11 cua Wayland),
    # trang thai Qt.WindowMaximized bi WM bo qua hoan toan du goi bao nhieu
    # lan/luc nao - giai phap chac chan hon la TU set kich thuoc cua so bang
    # dung kich thuoc man hinh hien tai (khong dua vao WM hieu dung "maximize"
    # la gi nua). Van goi showMaximized() truoc (de co UI dung cua trang thai
    # maximized - vd nut khoi phuc) roi ghi de bang geometry man hinh day du.
    screen = app.primaryScreen()
    if screen is not None:
        win.setGeometry(screen.availableGeometry())
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
