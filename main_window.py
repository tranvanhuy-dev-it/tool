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

import os
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPlainTextEdit, QLabel, QRadioButton, QButtonGroup, QPushButton,
    QFileDialog, QStatusBar, QSplitter, QMessageBox, QSlider, QDoubleSpinBox,
    QSpinBox, QCheckBox, QColorDialog
)
from PyQt5.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QIcon
from PyQt5.QtCore import Qt
import re

from gcode_parser import parse_gcode
from canvas_widget import CanvasWidget
from gcode_editor import GcodeEditor


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
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))
        self.resize(1400, 850)

        self.absolute_mode = True   # True = G90, False = G91
        self.last_ref_point = (0.0, 0.0)  # diem tham chieu cho che do tuong doi
        self._base_app_font_pt = QApplication.font().pointSize()
        self.ui_scale_pct = 100

        self._build_ui()
        self._connect_signals()
        self._refresh_color_swatches()
        self.btn_dark_mode.setChecked(True)  # mac dinh mo che do toi
        self._render()

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
        self.spin_decimals.setValue(3)
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
        self.spin_grid.setValue(5.0)
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
        left_layout.addWidget(self.editor)
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
        self.canvas = CanvasWidget()
        right_layout.addWidget(self.canvas)
        splitter.addWidget(right)

        splitter.setSizes([600, 800])

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
        self.editor.textChanged.connect(self._render)
        self.canvas.point_clicked.connect(self._on_canvas_clicked)
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
        self.status.showMessage(
            "Đã tải ảnh. Đã tự đặt Cao phôi theo đúng tỷ lệ khung hình. "
            "Chỉnh lại Rộng/Cao phôi và giá trị a (X, Y) nếu cần cho khớp bản vẽ thật."
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
        self.editor.setPlainText("G90\n")
        self.last_ref_point = (0.0, 0.0)
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
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể mở file: {e}")

    def _save_file(self):
        start_path = os.path.join(os.path.expanduser("~"), "program.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu chương trình G-code", start_path, "Text files (*.txt);;All files (*)")
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
    win.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
