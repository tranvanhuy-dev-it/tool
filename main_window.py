"""
Cua so chinh: ghep trinh soan thao G-code (trai) va canvas xem truoc (phai).

Luong hoat dong:
  1. Nguoi dung go G-code vao editor (dinh dang .txt chuan de nap may CNC).
  2. Moi khi noi dung thay doi -> parse lai toan bo -> ve lai canvas.
  3. Nguoi dung click chuot vao canvas tai mot vi tri bat ky:
       - He TUYET DOI (G90): chen "X.. Y.." la toa do thuc te tai diem click.
       - He TUONG DOI (G91): chen "X.. Y.." la do lech so voi diem click TRUOC DO
         (hoac so voi vi tri dao hien tai neu chua co lan click nao).
     Chuoi toa do duoc chen dung vao VI TRI CON TRO trong editor.
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPlainTextEdit, QLabel, QRadioButton, QButtonGroup, QPushButton,
    QFileDialog, QStatusBar, QSplitter, QMessageBox, QSlider, QDoubleSpinBox,
    QGroupBox, QFrame, QSizePolicy, QSpinBox, QCheckBox
)
from PyQt5.QtGui import QFont, QTextCursor, QSyntaxHighlighter, QTextCharFormat, QColor
from PyQt5.QtCore import Qt

from gcode_parser import parse_gcode
from canvas_widget import CanvasWidget

# --- 2 bang mau: toi (dark) va sang (light), kieu phan mem CAD/CAM cong nghiep ---
THEMES = {
    "dark": dict(
        bg="#1e1f22", panel="#26282b", panel_alt="#2d2f33", border="#3c3f44",
        text="#d4d6d9", text_dim="#8b8f96", accent="#3b9eff", editor_bg="#1b1c1e",
    ),
    "light": dict(
        bg="#eef0f2", panel="#f7f8fa", panel_alt="#ffffff", border="#c7cbd1",
        text="#20232a", text_dim="#5b6068", accent="#0b6bcb", editor_bg="#ffffff",
    ),
}

# --- co so kich thuoc chu: nhan voi he so phong to/thu nho cua nguoi dung ---
BASE_FONT_PX = 20
BASE_LABEL_PX = 18
BASE_HEADER_PX = 16
BASE_HINT_PX = 13
BASE_EDITOR_PT = 16


def build_stylesheet(c: dict, scale: float) -> str:
    f = lambda px: max(8, round(px * scale))
    return f"""
QMainWindow, QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: "Segoe UI", "Noto Sans", sans-serif;
    font-size: {f(BASE_FONT_PX)}px;
}}
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 4px;
    margin-top: {f(14)}px;
    padding: {f(8)}px;
    background-color: {c['panel']};
    font-weight: 600;
    color: {c['text_dim']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: {f(10)}px;
    padding: 0 {f(5)}px;
    color: {c['text_dim']};
    letter-spacing: 0.5px;
    text-transform: uppercase;
    font-size: {f(BASE_HEADER_PX)}px;
}}
QLabel {{
    color: {c['text_dim']};
    font-size: {f(BASE_LABEL_PX)}px;
}}
QPushButton {{
    background-color: {c['panel_alt']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: {f(7)}px {f(14)}px;
    color: {c['text']};
    font-size: {f(BASE_LABEL_PX)}px;
}}
QPushButton:hover {{
    background-color: {c['accent']};
    border-color: {c['accent']};
    color: #ffffff;
}}
QPushButton:pressed {{
    background-color: {c['border']};
}}
QPushButton#scaleBtn {{
    font-weight: 700;
    padding: {f(6)}px {f(10)}px;
    min-width: {f(22)}px;
}}
QDoubleSpinBox, QSpinBox {{
    background-color: {c['editor_bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: {f(4)}px {f(5)}px;
    color: {c['accent']};
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: {f(BASE_LABEL_PX)}px;
}}
QDoubleSpinBox:focus, QSpinBox:focus {{
    border-color: {c['accent']};
}}
QRadioButton, QCheckBox {{
    color: {c['text']};
    font-size: {f(BASE_LABEL_PX)}px;
    spacing: {f(6)}px;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: {f(14)}px; height: {f(14)}px;
}}
QPlainTextEdit {{
    background-color: {c['editor_bg']};
    color: {c['text']};
    border: 1px solid {c['border']};
    selection-background-color: {c['accent']};
    selection-color: #ffffff;
}}
QSplitter::handle {{
    background-color: {c['border']};
    width: 3px;
}}
QStatusBar {{
    background-color: {c['panel']};
    color: {c['text_dim']};
    border-top: 1px solid {c['border']};
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-size: {f(BASE_LABEL_PX)}px;
}}
QLabel#mouseCoord {{
    color: {c['accent']};
    font-family: "Consolas", "JetBrains Mono", monospace;
    font-weight: 700;
    font-size: {f(BASE_LABEL_PX)}px;
    padding: 0 {f(10)}px;
}}
QSlider::groove:horizontal {{
    background: {c['border']};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {c['accent']};
    width: {f(13)}px;
    margin: {f(-5)}px 0;
    border-radius: {f(7)}px;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {c['panel']};
    width: {f(13)}px; height: {f(13)}px;
}}
QScrollBar::handle {{
    background: {c['border']};
    border-radius: {f(5)}px;
    min-height: {f(24)}px;
}}
QScrollBar::handle:hover {{
    background: {c['accent']};
}}
"""


class GcodeHighlighter(QSyntaxHighlighter):
    """To mau co ban cho G-code: khong dung AI, chi la regex + QTextCharFormat."""

    def __init__(self, document, dark: bool = True):
        super().__init__(document)
        self.set_theme(dark)

    def set_theme(self, dark: bool):
        self.fmt_g = QTextCharFormat()
        self.fmt_g.setForeground(QColor("#4da3ff" if dark else "#0b5fbf"))
        self.fmt_g.setFontWeight(QFont.Bold)

        self.fmt_coord = QTextCharFormat()
        self.fmt_coord.setForeground(QColor("#3ecf8e" if dark else "#0f7a4c"))

        self.fmt_comment = QTextCharFormat()
        self.fmt_comment.setForeground(QColor("#8b8f96" if dark else "#8a8f98"))
        self.fmt_comment.setFontItalic(True)
        self.rehighlight()

    def highlightBlock(self, text):
        import re
        for m in re.finditer(r"\bG\d+\b|\bM\d+\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_g)
        for m in re.finditer(r"\b[XYZIJF]-?\d+\.?\d*\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_coord)
        for m in re.finditer(r";.*$|\([^)]*\)", text):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_comment)


class MainWindow(QMainWindow):
    SCALE_MIN = 0.7
    SCALE_MAX = 3.0
    SCALE_STEP = 0.1

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CNC G-code Designer — Soạn thảo & Xem trước")
        self.resize(1500, 900)

        self.absolute_mode = True   # True = G90, False = G91
        self.last_ref_point = (0.0, 0.0)  # diem tham chieu cho che do tuong doi
        self.ui_scale = 1.0
        self.theme_name = "dark"

        self._build_ui()
        self._connect_signals()
        self._apply_theme()
        self._render()

    # ---------------- UI ----------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- thanh cong cu ky thuat: mot day gom nhieu nhom chuc nang ---
        self.toolbar = QWidget()
        toolbar_layout = QHBoxLayout(self.toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(12)
        self._toolbar_layout = toolbar_layout

        # nhom: File
        grp_file = QGroupBox("Tệp")
        l = QHBoxLayout(grp_file)
        l.setContentsMargins(10, 14, 10, 8)
        l.setSpacing(8)
        self.btn_open = QPushButton("Mở G-code")
        self.btn_save = QPushButton("Xuất G-code (.txt)")
        l.addWidget(self.btn_open)
        l.addWidget(self.btn_save)
        toolbar_layout.addWidget(grp_file)

        # nhom: he toa do
        grp_coord = QGroupBox("Hệ tọa độ khi click")
        l = QHBoxLayout(grp_coord)
        l.setContentsMargins(10, 14, 10, 8)
        l.setSpacing(8)
        self.radio_abs = QRadioButton("Tuyệt đối · G90")
        self.radio_rel = QRadioButton("Tương đối · G91")
        self.radio_abs.setChecked(True)
        coord_group = QButtonGroup(self)
        coord_group.addButton(self.radio_abs)
        coord_group.addButton(self.radio_rel)
        l.addWidget(self.radio_abs)
        l.addWidget(self.radio_rel)

        l.addWidget(self._vsep())
        l.addWidget(QLabel("Số TP"))
        self.spin_decimals = QSpinBox()
        self.spin_decimals.setRange(0, 6)
        self.spin_decimals.setValue(3)
        self.spin_decimals.setProperty("baseWidth", 56)
        self.spin_decimals.setMinimumWidth(56)
        l.addWidget(self.spin_decimals)

        l.addWidget(self._vsep())
        self.chk_snap = QCheckBox("Hút lưới")
        self.chk_snap.setChecked(True)
        l.addWidget(self.chk_snap)

        toolbar_layout.addWidget(grp_coord)

        # nhom: anh ban ve tham chieu
        grp_img = QGroupBox("Ảnh bản vẽ tham chiếu")
        l = QHBoxLayout(grp_img)
        l.setContentsMargins(10, 14, 10, 8)
        l.setSpacing(8)
        self.btn_load_image = QPushButton("Tải ảnh...")
        l.addWidget(self.btn_load_image)

        l.addWidget(self._vsep())
        self.spin_width = self._labeled_spin(l, "Rộng", 0.01, 100000, 2, 100.0, 84)
        self.spin_height = self._labeled_spin(l, "Cao", 0.01, 100000, 2, 100.0, 84)

        l.addWidget(self._vsep())
        self.spin_ax = self._labeled_spin(l, "a·X", -100000, 100000, 3, 0.0, 76)
        self.spin_ay = self._labeled_spin(l, "a·Y", -100000, 100000, 3, 0.0, 76)

        l.addWidget(self._vsep())
        self.spin_grid = self._labeled_spin(l, "Ô lưới", 0.01, 10000, 2, 5.0, 70)

        l.addWidget(self._vsep())
        l.addWidget(QLabel("Độ mờ"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.setValue(50)
        self.slider_opacity.setProperty("baseWidth", 100)
        self.slider_opacity.setMinimumWidth(100)
        l.addWidget(self.slider_opacity)

        toolbar_layout.addWidget(grp_img)
        toolbar_layout.addStretch()

        # nhom: hien thi (thu phong giao dien + sang/toi)
        grp_view = QGroupBox("Giao diện")
        l = QHBoxLayout(grp_view)
        l.setContentsMargins(10, 14, 10, 8)
        l.setSpacing(6)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setObjectName("scaleBtn")
        self.lbl_zoom_pct = QLabel("100%")
        self.lbl_zoom_pct.setProperty("baseWidth", 60)
        self.lbl_zoom_pct.setMinimumWidth(60)
        self.lbl_zoom_pct.setAlignment(Qt.AlignCenter)
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setObjectName("scaleBtn")
        l.addWidget(self.btn_zoom_out)
        l.addWidget(self.lbl_zoom_pct)
        l.addWidget(self.btn_zoom_in)

        l.addWidget(self._vsep())
        self.btn_theme = QPushButton("☾ Tối")
        l.addWidget(self.btn_theme)

        toolbar_layout.addWidget(grp_view)

        root.addWidget(self.toolbar)

        # --- dong ghi chu thao tac (hint bar), kieu status line cua phan mem CAM ---
        self.hint_bar = QWidget()
        hint_layout = QHBoxLayout(self.hint_bar)
        hint_layout.setContentsMargins(12, 5, 12, 5)
        self.lbl_hint = QLabel(
            "Chuột trái: chèn tọa độ  ·  Chuột phải: hoàn tác  ·  "
            "Ctrl+kéo: di chuyển  ·  Cuộn: thu phóng"
        )
        hint_layout.addWidget(self.lbl_hint)
        hint_layout.addStretch()
        root.addWidget(self.hint_bar)

        # --- vung chinh: splitter 2 cot ---
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, stretch=1)

        # cot trai: editor
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        self.header_left = self._panel_header("Chương trình G-code (.txt)")
        left_layout.addWidget(self.header_left)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("G90\nG0 X0 Y0\nG1 X50 Y0\nG1 X50 Y30\n...")
        self.editor.setPlainText(
            "; Chuong trinh mau - phay khoi hop 100x60mm co 4 lo goc\n"
            "G90\n"
            "G0 X0 Y0\n"
            "G1 X100 Y0\n"
            "G1 X100 Y60\n"
            "G1 X0 Y60\n"
            "G1 X0 Y0\n"
        )
        self.editor.setFrameShape(QFrame.NoFrame)
        self.highlighter = GcodeHighlighter(self.editor.document(), dark=True)
        left_layout.addWidget(self.editor)
        splitter.addWidget(left)

        # cot phai: canvas
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.header_right = self._panel_header("Xem trước đường chạy dao")
        right_layout.addWidget(self.header_right)
        self.canvas = CanvasWidget()
        self.canvas.setFrameShape(QFrame.NoFrame)
        right_layout.addWidget(self.canvas)
        splitter.addWidget(right)

        splitter.setSizes([650, 850])

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Sẵn sàng.")

        # o hien thi toa do theo thoi gian thuc khi di chuot (kieu DRO tren may CNC that),
        # dat co dinh o ben phai status bar, tach rieng khoi cac thong bao showMessage()
        # de khong bi xung dot/ghi de qua lien tuc.
        self.lbl_mouse_coord = QLabel("X — Y —")
        self.lbl_mouse_coord.setObjectName("mouseCoord")
        self.status.addPermanentWidget(self.lbl_mouse_coord)

    @staticmethod
    def _vsep() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setObjectName("vsep")
        return sep

    @staticmethod
    def _panel_header(text: str) -> QWidget:
        header = QWidget()
        header.setObjectName("panelHeader")
        header.setFixedHeight(32)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 12, 0)
        lbl = QLabel(text)
        lbl.setObjectName("panelHeaderLabel")
        hl.addWidget(lbl)
        hl.addStretch()
        header._label = lbl
        return header

    @staticmethod
    def _labeled_spin(layout: QHBoxLayout, label: str, lo: float, hi: float,
                       decimals: int, value: float, width: int) -> QDoubleSpinBox:
        layout.addWidget(QLabel(label))
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setProperty("baseWidth", width)
        spin.setMinimumWidth(width)
        layout.addWidget(spin)
        return spin

    def _connect_signals(self):
        self.editor.textChanged.connect(self._render)
        self.canvas.point_clicked.connect(self._on_canvas_clicked)
        self.canvas.undo_requested.connect(self._on_canvas_undo)
        self.canvas.mouse_moved_mm.connect(self._on_canvas_mouse_moved)
        self.chk_snap.toggled.connect(self.canvas.set_snap_enabled)
        self.radio_abs.toggled.connect(self._on_mode_toggled)
        self.btn_open.clicked.connect(self._open_file)
        self.btn_save.clicked.connect(self._save_file)

        self.btn_load_image.clicked.connect(self._load_drawing_image)
        self.spin_width.valueChanged.connect(self._on_image_params_changed)
        self.spin_height.valueChanged.connect(self._on_image_params_changed)
        self.spin_ax.valueChanged.connect(self._on_image_params_changed)
        self.spin_ay.valueChanged.connect(self._on_image_params_changed)
        self.spin_grid.valueChanged.connect(self._on_image_params_changed)
        self.slider_opacity.valueChanged.connect(
            lambda v: (self.canvas.set_background_opacity(v / 100.0), self._render())
        )

        self.btn_zoom_in.clicked.connect(lambda: self._change_ui_scale(self.SCALE_STEP))
        self.btn_zoom_out.clicked.connect(lambda: self._change_ui_scale(-self.SCALE_STEP))
        self.btn_theme.clicked.connect(self._toggle_theme)

    # ---------------- giao dien: thu phong + sang/toi ----------------

    def _change_ui_scale(self, delta: float):
        new_scale = round(min(self.SCALE_MAX, max(self.SCALE_MIN, self.ui_scale + delta)), 2)
        if new_scale == self.ui_scale:
            return
        self.ui_scale = new_scale
        self._apply_theme()

    def _toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self._apply_theme()

    def _apply_theme(self):
        c = THEMES[self.theme_name]
        dark = self.theme_name == "dark"

        self.setStyleSheet(build_stylesheet(c, self.ui_scale))
        self.lbl_zoom_pct.setText(f"{round(self.ui_scale * 100)}%")
        self.btn_theme.setText("☀ Sáng" if dark else "☾ Tối")

        f = lambda px: max(8, round(px * self.ui_scale))

        self.toolbar.setStyleSheet(
            f"background-color: {c['panel']}; border-bottom: 1px solid {c['border']};")
        self.hint_bar.setStyleSheet(
            f"background-color: {c['bg']}; border-bottom: 1px solid {c['border']};")
        self.lbl_hint.setStyleSheet(
            f"color: {c['text_dim']}; font-size: {f(BASE_HINT_PX)}px; letter-spacing: 0.3px;")

        for sep in self.findChildren(QFrame, "vsep"):
            sep.setStyleSheet(f"color: {c['border']};")

        for header in (self.header_left, self.header_right):
            header.setStyleSheet(
                f"background-color: {c['panel']}; border-bottom: 1px solid {c['border']};")
            header._label.setStyleSheet(
                f"color: {c['text_dim']}; font-size: {f(BASE_HEADER_PX)}px; "
                f"font-weight: 600; letter-spacing: 0.8px;")

        self.editor.setFont(QFont("Consolas", round(BASE_EDITOR_PT * self.ui_scale)))
        self.highlighter.set_theme(dark)

        # cac o nhap/nhan co do rong co dinh (Rong, Cao, a-X, a-Y, So TP, %zoom...)
        # phai duoc noi rong theo cung he so scale, neu khong chu se bi cat/che khi
        # phong to giao dien (baseWidth duoc luu san luc tao widget).
        for w in self.findChildren(QWidget):
            base_w = w.property("baseWidth")
            if base_w is not None:
                w.setMinimumWidth(round(base_w * self.ui_scale))

        self.status.showMessage(self.status.currentMessage() or "Sẵn sàng.")

    # ---------------- logic ----------------

    def _on_mode_toggled(self, checked):
        self.absolute_mode = self.radio_abs.isChecked()

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
        self.status.showMessage(
            f"{len(result.segments)} đoạn di chuyển | Vị trí dao hiện tại: "
            f"X{result.end_x:.{nd}f} Y{result.end_y:.{nd}f}"
        )

    # ---------------- anh ban ve tham chieu ----------------
    #
    # Quy uoc: nguoi dung tu crop anh (ben ngoai app) sao cho anh khop khit voi
    # khung ngoai cua phoi (khong con le du). Sau khi tai anh len, nhap:
    #   - Rong/Cao phoi (mm): kich thuoc THUC TE ma toan bo be rong/chieu cao anh dai dien
    #   - a (X), a (Y): do lech (mm) tu goc DUOI-TRAI cua anh den goc toa do gia cong that (0,0)
    # He thong tu tinh ty le px/mm rieng cho tung truc va cong offset a khi quy doi
    # toa do pixel click sang toa do thuc, roi chen vao editor.

    def _load_drawing_image(self):
        import os
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

        # tu dong dat Cao phoi theo dung ty le khung hinh that cua anh, ung voi
        # Rong phoi dang nhap - de anh KHONG bi keo gian/meo khi vua tai len.
        # Nguoi dung van co the sua lai neu biet ro kich thuoc thuc te khac ty le nay.
        img_w = self.canvas._bg_image_w_px
        img_h = self.canvas._bg_image_h_px
        if img_w > 0:
            suggested_height = self.spin_width.value() * (img_h / img_w)
            self.spin_height.blockSignals(True)
            self.spin_height.setValue(suggested_height)
            self.spin_height.blockSignals(False)

        self._on_image_params_changed()
        self.status.showMessage(
            "Đã tải ảnh. Đã tự đặt Cao phôi theo đúng tỷ lệ khung hình (tránh méo ảnh). "
            "Chỉnh lại Rộng/Cao phôi (mm) và giá trị a (X, Y) nếu cần cho khớp bản vẽ thật."
        )

    def _on_image_params_changed(self):
        self.canvas.set_workpiece_size(self.spin_width.value(), self.spin_height.value())
        self.canvas.set_offset_a(self.spin_ax.value(), self.spin_ay.value())
        self.canvas.set_grid_step(self.spin_grid.value())
        self._render()

    def _on_canvas_clicked(self, x_mm: float, y_mm: float):
        """Chen toa do vao vi tri con tro hien tai trong editor."""
        nd = self.spin_decimals.value()
        if self.absolute_mode:
            snippet = f"X{x_mm:.{nd}f} Y{y_mm:.{nd}f}"
        else:
            ref_x, ref_y = self.last_ref_point
            dx = x_mm - ref_x
            dy = y_mm - ref_y
            snippet = f"X{dx:.{nd}f} Y{dy:.{nd}f}"

        cursor = self.editor.textCursor()
        cursor.insertText(snippet)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

        # cap nhat diem tham chieu cho lan click tuong doi tiep theo
        self.last_ref_point = (x_mm, y_mm)
        self.status.showMessage(
            f"Đã chèn: {snippet}  (click tại X{x_mm:.{nd}f} Y{y_mm:.{nd}f} tuyệt đối) — "
            f"chuột phải trên bản vẽ để hoàn tác"
        )

    def _on_canvas_undo(self):
        """Chuot phai tren canvas -> hoan tac thao tac soan thao gan nhat
        (dung co che Undo co san cua QPlainTextEdit, bao gom ca cac lan chen toa do)."""
        self.editor.undo()
        self.status.showMessage("Đã hoàn tác thao tác gần nhất.")

    def _on_canvas_mouse_moved(self, x_mm: float, y_mm: float):
        """Cap nhat o DRO ben phai status bar theo vi tri con tro hien tai
        (da snap vao giao diem luoi neu du gan), khong lam gian doan cac
        thong bao khac hien tren status bar."""
        nd = self.spin_decimals.value()
        self.lbl_mouse_coord.setText(f"X {x_mm:.{nd}f}   Y {y_mm:.{nd}f}")

    # ---------------- file I/O ----------------

    def _open_file(self):
        import os
        start_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở chương trình G-code", start_dir, "Text files (*.txt *.nc *.gcode);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể mở file: {e}")

    def _save_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu chương trình G-code", "program.txt", "Text files (*.txt);;All files (*)",
            options=QFileDialog.DontUseNativeDialog)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.editor.toPlainText())
            self.status.showMessage(f"Đã lưu: {path}")
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể lưu file: {e}")


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
