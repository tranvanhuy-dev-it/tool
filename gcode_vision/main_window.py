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
    QSpinBox, QCheckBox, QColorDialog, QGridLayout, QComboBox, QTextEdit,
)
from PyQt5.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QIcon, QKeySequence, QTextFormat
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QShortcut, QTableWidget, QTableWidgetItem, QAbstractItemView, QFrame
import re
import datetime
import shutil

from gcode_vision.gcode_parser import (
    parse_gcode, convert_gcode_mode, estimate_machining_time_seconds,
    arc_to_polyline, ParseResult
)
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
        # Tu dong thiet lap geometry ban dau vua khit man hinh kha dung
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail is not None:
            self.setGeometry(avail)
        else:
            self.resize(1366, 768)

        self.absolute_mode = True   # True = G90, False = G91
        self.last_ref_point = (0.0, 0.0)  # diem tham chieu cho che do tuong doi
        self._last_inserted_coord = None  # (vi_tri_bat_dau, do_dai) cua doan X/Y vua chen, de "hoan tac" chi xoa dung phan nay
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

        # --- Mo phong chuyen dong mui dao CNC ---
        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(33)  # ~30 FPS
        self._sim_timer.timeout.connect(self._sim_tick)
        self._sim_running = False
        self._sim_trajectory = []
        self._sim_total_duration = 0.0
        self._sim_current_time = 0.0
        self._sim_speed_multiplier = 1.0
        self._sim_is_seeking = False
        self._last_highlighted_sim_line = None

        self._build_ui()
        self._connect_signals()
        self._refresh_color_swatches()
        # setChecked() CHI phat tin hieu toggled neu gia tri THAY DOI so voi
        # hien tai - vi QPushButton.setCheckable(True) mac dinh la False, goi
        # setChecked(False) o day KHONG kich hoat _toggle_dark_mode(), nen goi
        # TUONG MINH de dam bao moi phan cua UI (bao gom GcodeEditor._is_dark_mode)
        # luon dong bo dung trang thai NGAY TU DAU, khong phu thuoc gia tri
        # mac dinh "cung" o noi khac co khop hay khong.
        self.btn_dark_mode.setChecked(False)
        self._toggle_dark_mode(False)

        # Noi dung mac dinh khi vua mo app: dong G90 (che do tuyet doi, dung
        # theo self.absolute_mode mac dinh = True) - GIONG HET hanh vi "Tao
        # moi", de nguoi dung khong phai tu go dong nay moi lan mo ung dung.
        # Goi block/unblock tin hieu textChanged de KHONG bi danh dau "chua
        # luu" (_dirty=True) chi vi dong mac dinh nay - _dirty chi nen bat khi
        # NGUOI DUNG thuc su go them noi dung.
        mode_line = "G90" if self.absolute_mode else "G91"
        self.editor.blockSignals(True)
        self.editor.setPlainText(mode_line + "\n")
        self.editor.blockSignals(False)

        self._render()

        self._setup_autosave()
        self._offer_restore_autosave()  # co the GHI DE lai bang ban nhap cu neu nguoi dung dong y
        self._setup_shortcuts()
        self._update_window_title()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'splitter'):
            w = self.splitter.width()
            if w > 100:
                self.splitter.setSizes([round(w / 3.0), round(w * 2.0 / 3.0)])
        QTimer.singleShot(60, self.canvas.fit_view)

    # ---------------- UI ----------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        # Bo HOAN TOAN margin mac dinh (~9-11px) cua QVBoxLayout - de canh
        # TRAI/PHAI cua noi dung chinh (splitter chua editor/canvas) SAT MEP
        # cua so y HET nhu QStatusBar duoi cung (status bar do QMainWindow tu
        # quan ly, khong co margin ngoai), tranh lech cot giua 2 khu vuc.
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.settings_panel = self._build_settings_panel()
        root.addWidget(self.settings_panel)

        # --- vung chinh: splitter 2 cot ---
        self.splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self.splitter, stretch=1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Chương trình G-code (.txt)"))

        self.editor = GcodeEditor()
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setPlaceholderText("G90\nG0 X0 Y0\nG1 X50 Y0\nG1 X50 Y30\n...")
        self.highlighter = GcodeHighlighter(self.editor.document())

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(self.editor)

        # Bang danh sach diem VAN duoc tao (nhieu noi khac trong code van cap
        # nhat/doc no, vd khi highlight dong dang mo phong) nhung KHONG hien
        # thi tren giao dien nua - de vung soan thao G-code chiem toan bo
        # chieu cao cot trai, thoang va tap trung hon.
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
        points_panel.setVisible(False)
        left_splitter.addWidget(points_panel)

        # Bang "Duong do da luu" tu cong cu Do khoang cach: moi lan do xong
        # (click du 2 diem), CA DUONG (2 toa do + khoang cach) duoc them vao
        # day. Duong tuong ung cung duoc VE VINH VIEN tren canvas (xem
        # canvas.add_saved_measure_line), xoa 1 dong trong bang se xoa CA
        # DUONG do khoi canvas. Panel nay CHI HIEN khi co it nhat 1 dong -
        # AN HOAN TOAN (khong chiem khong gian gi) khi bang rong, xem
        # _update_pinned_panel_visibility() duoc goi moi lan bang thay doi.
        self.pinned_panel = QWidget()
        pinned_layout = QVBoxLayout(self.pinned_panel)
        pinned_layout.setContentsMargins(0, 0, 0, 0)
        pinned_layout.addWidget(QLabel("Đường đo đã lưu"))
        self.table_pinned_points = QTableWidget(0, 4)
        self.table_pinned_points.setHorizontalHeaderLabels(["Điểm 1", "Điểm 2", "Khoảng cách", ""])
        self.table_pinned_points.horizontalHeader().setStretchLastSection(False)
        self.table_pinned_points.setColumnWidth(3, 30)
        self.table_pinned_points.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_pinned_points.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_pinned_points.verticalHeader().setVisible(False)
        pinned_layout.addWidget(self.table_pinned_points)
        btn_clear_pinned = QPushButton("Xoá tất cả")
        self.btn_clear_pinned_points = btn_clear_pinned
        pinned_layout.addWidget(btn_clear_pinned)
        self.pinned_panel.setVisible(False)
        left_splitter.addWidget(self.pinned_panel)

        left_splitter.setSizes([1, 0, 260])
        left_splitter.setStretchFactor(0, 1)
        left_splitter.setStretchFactor(1, 0)
        left_splitter.setStretchFactor(2, 0)

        left_layout.addWidget(left_splitter)
        self.splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_header = QHBoxLayout()
        right_header.addWidget(QLabel("Xem trước đường chạy dao"))
        right_header.addSpacing(14)

        # Cum dieu khien mo phong mui dao CNC
        # Chieu cao CO DINH chung cho ca 4 nut (Chay thu + 3 nut icon) - neu
        # khong moi nut se co sizeHint() rieng theo font/noi dung cua no (nut
        # chu "Chay thu" dung font mac dinh, 3 nut icon dung font khac) va bi
        # LECH chieu cao ro ret khi dat canh nhau tren cung 1 hang.
        SIM_BTN_HEIGHT = 34

        self.btn_sim_play = QPushButton("▶ Chạy thử")
        self.btn_sim_play.setToolTip("Bắt đầu / Tạm dừng mô phỏng chuyển động mũi dao")
        self.btn_sim_play.setMinimumWidth(85)
        self.btn_sim_play.setFixedHeight(SIM_BTN_HEIGHT)
        self.btn_sim_play.setStyleSheet("color: #16a34a; font-weight: bold;")
        right_header.addWidget(self.btn_sim_play)

        btn_ctrl_font = QFont()
        btn_ctrl_font.setPointSize(11)

        self.btn_sim_stop = QPushButton("⏹")
        self.btn_sim_stop.setObjectName("sim_ctrl")
        self.btn_sim_stop.setFont(btn_ctrl_font)
        self.btn_sim_stop.setToolTip("Dừng mô phỏng và về điểm đầu")
        self.btn_sim_stop.setMinimumWidth(34)
        self.btn_sim_stop.setFixedHeight(SIM_BTN_HEIGHT)
        self.btn_sim_stop.setStyleSheet("color: #dc2626; font-weight: bold;")
        right_header.addWidget(self.btn_sim_stop)

        self.btn_sim_prev = QPushButton("⏮")
        self.btn_sim_prev.setObjectName("sim_ctrl")
        self.btn_sim_prev.setFont(btn_ctrl_font)
        self.btn_sim_prev.setToolTip("Lùi 1 câu lệnh")
        self.btn_sim_prev.setMinimumWidth(34)
        self.btn_sim_prev.setFixedHeight(SIM_BTN_HEIGHT)
        right_header.addWidget(self.btn_sim_prev)

        self.btn_sim_step = QPushButton("⏭")
        self.btn_sim_step.setObjectName("sim_ctrl")
        self.btn_sim_step.setFont(btn_ctrl_font)
        self.btn_sim_step.setToolTip("Tiến 1 câu lệnh")
        self.btn_sim_step.setMinimumWidth(34)
        self.btn_sim_step.setFixedHeight(SIM_BTN_HEIGHT)
        right_header.addWidget(self.btn_sim_step)

        self.slider_sim_progress = QSlider(Qt.Horizontal)
        self.slider_sim_progress.setRange(0, 1000)
        self.slider_sim_progress.setValue(0)
        self.slider_sim_progress.setFixedWidth(120)
        self.slider_sim_progress.setToolTip("Tua nhanh tiến trình mô phỏng")
        right_header.addWidget(self.slider_sim_progress)

        self.combo_sim_speed = QComboBox()
        self.combo_sim_speed.addItems(["0.5x", "1x", "2x", "5x", "10x"])
        self.combo_sim_speed.setCurrentText("1x")
        self.combo_sim_speed.setFixedWidth(80)
        self.combo_sim_speed.setToolTip("Tốc độ chạy mô phỏng")
        right_header.addWidget(self.combo_sim_speed)

        self.lbl_sim_hud = QLabel("")
        hud_font = QFont("Consolas", 10)
        hud_font.setBold(True)
        self.lbl_sim_hud.setFont(hud_font)
        self.lbl_sim_hud.setStyleSheet("color: #10b981;")
        right_header.addWidget(self.lbl_sim_hud)

        right_header.addStretch()

        # Toa do chuot: day sat qua mep phai cua hang
        self.lbl_mouse_coord = QLabel("X —   Y —")
        coord_font = QFont("Consolas", 9)
        coord_font.setBold(True)
        self.lbl_mouse_coord.setFont(coord_font)
        self.lbl_mouse_coord.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_mouse_coord.setMinimumWidth(100)
        right_header.addWidget(self.lbl_mouse_coord)

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
        self.splitter.addWidget(right)

        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        total_w = avail.width() if avail else 1400
        left_w = round(total_w / 3.0)
        right_w = total_w - left_w
        self.splitter.setSizes([left_w, right_w])
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Sẵn sàng.")

        # Link website, zoom UI, dark mode - dat CUNG HANG voi status bar
        # duoi cung, o ben phai, bang addPermanentWidget() (widget "permanent"
        # luon o mep phai, khong bi de boi noi dung showMessage() tam thoi ben
        # trai) - KHONG dat rieng thanh 1 hang trong cot phai (se chiem mot
        # khoang khong gian rieng, lam mat can doi voi cot trai ben duoi).
        self.lbl_website = QLabel('<a href="https://www.tranvanhuy.io.vn">tranvanhuy.io.vn</a>')
        self.lbl_website.setOpenExternalLinks(True)
        self.status.addPermanentWidget(self.lbl_website)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setMinimumWidth(28)
        self.btn_zoom_out.setToolTip("Thu nhỏ giao diện")
        self.status.addPermanentWidget(self.btn_zoom_out)
        self.lbl_zoom_pct = QLabel("100%")
        self.lbl_zoom_pct.setMinimumWidth(44)
        self.lbl_zoom_pct.setAlignment(Qt.AlignCenter)
        self.status.addPermanentWidget(self.lbl_zoom_pct)
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setMinimumWidth(28)
        self.btn_zoom_in.setToolTip("Phóng to giao diện")
        self.status.addPermanentWidget(self.btn_zoom_in)

        self.btn_dark_mode = QPushButton("Chế độ tối")
        self.btn_dark_mode.setCheckable(True)
        self.status.addPermanentWidget(self.btn_dark_mode)

    @staticmethod
    def _vsep() -> QFrame:
        """Duong phan cach DOC mong, dung giua cac NHOM chuc nang khac nhau
        tren cung 1 hang - giup mat de nhan ra ranh gioi giua cac nhom, tranh
        cam giac moi widget dinh lien nhau thanh 1 khoi duy nhat kho doc."""
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        return sep

    def _build_settings_panel(self) -> QWidget:
        """Panel thiet lap chi tiet, LUON HIEN duoi toolbar - gom: he toa do
        khi click, tuy chon luoi/diem giao, anh ban ve tham chieu & phoi, mau
        net ve. Cac NHOM duoc ngan cach bang khoang trang RONG HON han so voi
        khoang cach GIUA CAC WIDGET trong cung 1 nhom, cong them 1 duong ke
        doc (_vsep) - de mat de phan biet ranh gioi nhom, tranh cam giac moi
        thu dinh lien nhau thanh 1 day dai kho doc/kho dung."""
        GROUP_GAP = 22   # khoang cach GIUA 2 NHOM khac nhau
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 6, 0, 6)
        panel_layout.setSpacing(10)

        # --- hang 1 cua panel: Tep + He toa do + Luoi/diem giao + Che do click + Danh so dong ---
        row1 = QHBoxLayout()
        row1.setSpacing(0)

        grp_file, l = self._section("Tệp")
        self.btn_new = QPushButton("Tạo mới")
        self.btn_open = QPushButton("Mở G-code")
        self.btn_save = QPushButton("Xuất G-code (.txt)")
        for b in (self.btn_new, self.btn_open, self.btn_save):
            l.addWidget(b)
        row1.addWidget(grp_file)
        row1.addSpacing(GROUP_GAP)
        row1.addWidget(self._vsep())
        row1.addSpacing(GROUP_GAP)

        grp_coord, l = self._section("Hệ tọa độ khi chèn điểm")
        self.radio_abs = QRadioButton("Tuyệt đối (G90)")
        self.radio_rel = QRadioButton("Tương đối (G91)")
        self.radio_abs.setChecked(True)
        coord_group = QButtonGroup(self)
        coord_group.addButton(self.radio_abs)
        coord_group.addButton(self.radio_rel)
        l.addWidget(self.radio_abs)
        l.addWidget(self.radio_rel)
        l.addSpacing(10)
        l.addWidget(QLabel("Số chữ số thập phân:"))
        self.spin_decimals = QSpinBox()
        self.spin_decimals.setRange(0, 6)
        self.spin_decimals.setValue(0)
        self.spin_decimals.setMinimumWidth(58)
        l.addWidget(self.spin_decimals)
        row1.addWidget(grp_coord)
        row1.addSpacing(GROUP_GAP)
        row1.addWidget(self._vsep())
        row1.addSpacing(GROUP_GAP)

        grp_snap, l = self._section("Lưới & điểm giao khi click")
        self.chk_snap = QCheckBox("Hút lưới")
        self.chk_snap.setChecked(True)
        l.addWidget(self.chk_snap)
        l.addWidget(QLabel("Cỡ điểm giao (px):"))
        self.spin_marker_size = QSpinBox()
        self.spin_marker_size.setRange(2, 40)
        self.spin_marker_size.setValue(9)
        self.spin_marker_size.setMinimumWidth(58)
        l.addWidget(self.spin_marker_size)
        row1.addWidget(grp_snap)
        row1.addSpacing(GROUP_GAP)
        row1.addWidget(self._vsep())
        row1.addSpacing(GROUP_GAP)

        grp_click_mode, l = self._section("Chế độ click trên bản vẽ")
        self.chk_measure_mode = QCheckBox("Đo khoảng cách (không chèn G-code)")
        self.chk_measure_mode.setChecked(False)  # mac dinh TAT - click canvas se chen toa do nhu binh thuong
        l.addWidget(self.chk_measure_mode)
        row1.addWidget(grp_click_mode)
        row1.addSpacing(GROUP_GAP)
        row1.addWidget(self._vsep())
        row1.addSpacing(GROUP_GAP)

        grp_autonum, l = self._section("Đánh số dòng (N)")
        self.chk_auto_n = QCheckBox("Tự động, bước:")
        self.chk_auto_n.setChecked(True)
        l.addWidget(self.chk_auto_n)
        self.spin_n_step = QSpinBox()
        self.spin_n_step.setRange(1, 1000)
        self.spin_n_step.setValue(1)
        self.spin_n_step.setMinimumWidth(65)
        l.addWidget(self.spin_n_step)
        row1.addWidget(grp_autonum)
        row1.addStretch()

        # --- hang 2 cua panel: Anh ban ve tham chieu & Phoi + Mau net ve ---
        row3 = QHBoxLayout()
        row3.setSpacing(0)

        grp_img, l = self._section("Ảnh bản vẽ tham chiếu & kích thước phôi")
        self.btn_load_image = QPushButton("Tải ảnh...")
        l.addWidget(self.btn_load_image)
        l.addWidget(QLabel("Rộng (mm):"))
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.01, 100000)
        self.spin_width.setDecimals(2)
        self.spin_width.setValue(100.0)
        self.spin_width.setMinimumWidth(95)
        l.addWidget(self.spin_width)
        l.addWidget(QLabel("Cao (mm):"))
        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(0.01, 100000)
        self.spin_height.setDecimals(2)
        self.spin_height.setValue(100.0)
        self.spin_height.setMinimumWidth(95)
        l.addWidget(self.spin_height)
        l.addSpacing(10)
        l.addWidget(QLabel("Offset gốc a(X, Y):"))
        self.spin_ax = QDoubleSpinBox()
        self.spin_ax.setRange(-100000, 100000)
        self.spin_ax.setDecimals(3)
        self.spin_ax.setMinimumWidth(90)
        l.addWidget(self.spin_ax)
        self.spin_ay = QDoubleSpinBox()
        self.spin_ay.setRange(-100000, 100000)
        self.spin_ay.setDecimals(3)
        self.spin_ay.setMinimumWidth(90)
        l.addWidget(self.spin_ay)
        l.addSpacing(10)
        l.addWidget(QLabel("Ô lưới (mm):"))
        self.spin_grid = QDoubleSpinBox()
        self.spin_grid.setRange(0.01, 10000)
        self.spin_grid.setDecimals(2)
        self.spin_grid.setValue(1.0)
        self.spin_grid.setMinimumWidth(85)
        l.addWidget(self.spin_grid)
        l.addWidget(QLabel("Độ mờ ảnh nền:"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(10, 100)
        self.slider_opacity.setValue(50)
        self.slider_opacity.setFixedWidth(90)
        l.addWidget(self.slider_opacity)
        row3.addWidget(grp_img)
        row3.addSpacing(GROUP_GAP)
        row3.addWidget(self._vsep())
        row3.addSpacing(GROUP_GAP)

        grp_colors, l = self._section("Màu nét vẽ")
        self._color_buttons = {}
        for key, label in (("cut", "Cắt"), ("rapid", "Chạy nhanh"),
                            ("grid", "Lưới"), ("axis", "Trục")):
            l.addWidget(QLabel(label))
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.clicked.connect(lambda _, k=key: self._pick_color(k))
            self._color_buttons[key] = btn
            l.addWidget(btn)
        row3.addWidget(grp_colors)
        row3.addStretch()

        panel_layout.addLayout(row1)
        panel_layout.addLayout(row3)
        return panel

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
        self.btn_clear_pinned_points.clicked.connect(self._clear_pinned_points)
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

        # Tin hieu mo phong mui dao CNC
        self.btn_sim_play.clicked.connect(self._sim_toggle_play)
        self.btn_sim_stop.clicked.connect(self._sim_stop)
        self.btn_sim_prev.clicked.connect(self._sim_step_backward)
        self.btn_sim_step.clicked.connect(self._sim_step_forward)
        self.slider_sim_progress.sliderMoved.connect(self._sim_on_slider_moved)
        self.slider_sim_progress.sliderPressed.connect(self._sim_on_slider_pressed)
        self.slider_sim_progress.sliderReleased.connect(self._sim_on_slider_released)
        self.combo_sim_speed.currentIndexChanged.connect(self._sim_on_speed_changed)

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
        self.editor.set_dark_mode(dark)
        if dark:
            self.setStyleSheet("""
                QWidget { background-color: #2b2b2b; color: #e0e0e0; }
                QPlainTextEdit { background-color: #1e1e1e; color: #dcdcdc; }
                QPushButton { background-color: #3c3c3c; border: 1px solid #555; padding: 6px 12px; }
                QPushButton:hover { background-color: #4a4a4a; }
                QPushButton:checked { background-color: #0a5a9c; }
                QPushButton#sim_ctrl { padding: 4px 6px; }
                QDoubleSpinBox, QSpinBox { background-color: #1e1e1e; color: #dcdcdc; border: 1px solid #555; padding: 2px 4px; }
                QComboBox { background-color: #1e1e1e; color: #dcdcdc; border: 1px solid #555; padding: 2px 6px; }
                QComboBox QAbstractItemView { background-color: #2b2b2b; color: #dcdcdc; selection-background-color: #0a5a9c; }
                QSlider::groove:horizontal { height: 4px; background: #555; border-radius: 2px; }
                QSlider::sub-page:horizontal { background: #10b981; border-radius: 2px; }
                QSlider::handle:horizontal { background: #e0e0e0; width: 12px; margin-top: -4px; margin-bottom: -4px; border-radius: 6px; }
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

        # Ep Qt tinh lai kich thuoc cac nut va spinbox theo padding moi cua stylesheet
        for w in self.findChildren((QPushButton, QSpinBox, QDoubleSpinBox, QComboBox)):
            w.updateGeometry()

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
            err_msg = str(e)
            self.status.showMessage(f"Lỗi phân tích G-code: {err_msg}")
            m = re.search(r"Dòng\s+(\d+)", err_msg)
            if m:
                self.editor.set_error_lines({int(m.group(1)): err_msg})
            return

        # TAM THOI AN hien thi canh bao (result.warnings - thieu F, thieu I/J...)
        # tren editor: khong con to do/hien icon ⚠/tooltip cho cac dong nay
        # nua. Logic parse+phat hien canh bao van chay binh thuong o duoi
        # (result.warnings van co du lieu), chi la KHONG dua vao
        # set_error_lines() nua. De bat lai: bo comment doan duoi va xoa
        # dong set_error_lines({}) ngay ben duoi.
        # error_lines = {}
        # for w in result.warnings:
        #     m = re.search(r"Dòng\s+(\d+)", w)
        #     if m:
        #         error_lines[int(m.group(1))] = w
        self.editor.set_error_lines({})

        # Truyen DUNG Rong/Cao phoi da khai bao (spin_width/spin_height) lam
        # sheet_w/sheet_h - de vung luoi/khung nhin LUON theo dung kich thuoc
        # phoi CO DINH nguoi dung da dat, KHONG tu dong co/gian theo pham vi
        # thuc te cua cac doan G-code hien co (truoc day khong truyen gi ca,
        # khien luoi bi "crop" vua khit diem xa nhat trong G-code, sai voi
        # kich thuoc phoi that su nguoi dung da nhap trong panel).
        self.canvas.render_program(
            result, sheet_w=self.spin_width.value(), sheet_h=self.spin_height.value())
        self.last_ref_point = (result.end_x, result.end_y)
        nd = self.spin_decimals.value()
        self._refresh_points_table(result.segments, nd)
        self._build_simulation_trajectory(result)

        time_str = self._format_machining_time(result.segments)
        # KHONG con noi canh bao (result.warnings) vao day nua - status bar chi
        # hien thong so gon gang (so doan, vi tri dao, thoi gian uoc tinh). Chi
        # tiet loi/canh bao tung dong da hien qua tooltip khi hover vao dong do
        # trong editor (xem set_error_lines() va GcodeEditor xu ly QEvent.ToolTip).
        msg = (
            f"{len(result.segments)} đoạn di chuyển | Vị trí dao hiện tại: "
            f"X{result.end_x:.{nd}f} Y{result.end_y:.{nd}f} | Ước tính thời gian: {time_str}"
        )
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

        # highlight diem tren canvas (mot dau cham don, khong ve doan noi) -
        # tai dung 1 diem thi khong can ve doan, chi can hien 1 marker TAM
        # THOI (preview) de nguoi dung thay ro vi tri, khong luu lai.
        self.canvas.show_measure_preview(x_mm, y_mm, x_mm, y_mm)

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
        self.canvas.clear_measure_preview()
        # Cac duong DA LUU (saved) khong bi dong cham gi khi bat/tat che do do
        # - chung tiep tuc hien thi tren canvas nhu binh thuong.
        if checked:
            self.status.showMessage("Chế độ đo khoảng cách: click điểm đầu, di chuột để xem trước, click điểm thứ hai để lưu.")

    def _on_canvas_clicked(self, x_mm: float, y_mm: float):
        if self.chk_measure_mode.isChecked():
            self._on_measure_click(x_mm, y_mm)
            return
        self._insert_coordinate(x_mm, y_mm)

    def _on_measure_click(self, x_mm: float, y_mm: float):
        """Cong cu do khoang cach/goc: click diem DAU, di chuyen chuot se
        thay duong noi + khoang cach bam theo con tro (preview), click diem
        THU HAI se LUU LAI duong do do VINH VIEN tren canvas + vao bang -
        KHONG chen gi vao G-code, chi la cong cu tham khao."""
        nd = self.spin_decimals.value()
        if self._measure_first_point is None:
            self._measure_first_point = (x_mm, y_mm)
            self.status.showMessage(
                f"Đo khoảng cách: điểm đầu X{x_mm:.{nd}f} Y{y_mm:.{nd}f} — "
                f"di chuyển chuột để xem trước, click điểm thứ hai để lưu."
            )
            return

        x0, y0 = self._measure_first_point
        dx = x_mm - x0
        dy = y_mm - y0
        dist = (dx * dx + dy * dy) ** 0.5
        angle_deg = math.degrees(math.atan2(dy, dx))
        self.canvas.clear_measure_preview()
        self._measure_first_point = None  # san sang cho phep do tiep theo

        self.status.showMessage(
            f"Đã lưu: khoảng cách {dist:.{nd}f} mm   Góc: {angle_deg:.2f}°   "
            f"(ΔX={dx:.{nd}f}  ΔY={dy:.{nd}f}) — click để đo đoạn mới."
        )
        self._save_measure_line(x0, y0, x_mm, y_mm, dist)

    def _on_measure_mouse_moved(self, x_mm: float, y_mm: float):
        """Cap nhat duong PREVIEW bam theo con tro trong luc dang cho click
        diem thu 2 - goi tu _on_canvas_mouse_moved() moi lan chuot di chuyen."""
        if self._measure_first_point is None:
            return
        x0, y0 = self._measure_first_point
        self.canvas.show_measure_preview(x0, y0, x_mm, y_mm)

    _next_measure_line_id = 0

    def _save_measure_line(self, x0, y0, x1, y1, dist):
        """Luu 1 duong do da hoan tat: them vao canvas (hien thi vinh vien)
        va vao bang danh sach ben trai."""
        MainWindow._next_measure_line_id += 1
        line_id = MainWindow._next_measure_line_id
        self.canvas.add_saved_measure_line(line_id, x0, y0, x1, y1, dist)

        nd = self.spin_decimals.value()
        row = self.table_pinned_points.rowCount()
        self.table_pinned_points.insertRow(row)
        self.table_pinned_points.setItem(row, 0, QTableWidgetItem(f"{x0:.{nd}f}, {y0:.{nd}f}"))
        self.table_pinned_points.setItem(row, 1, QTableWidgetItem(f"{x1:.{nd}f}, {y1:.{nd}f}"))
        self.table_pinned_points.setItem(row, 2, QTableWidgetItem(f"{dist:.{nd}f} mm"))
        btn_remove = QPushButton("✕")
        btn_remove.setFixedWidth(26)
        btn_remove.setToolTip("Xoá đường đo này")
        btn_remove.clicked.connect(lambda: self._remove_pinned_row(btn_remove, line_id))
        self.table_pinned_points.setCellWidget(row, 3, btn_remove)
        self._update_pinned_panel_visibility()

    def _remove_pinned_row(self, btn_remove, line_id):
        """Xoa dong bang tuong ung (tim theo cellWidget, khong theo index co
        dinh - vi cac dong khac co the da bi xoa lam lech index) VA xoa luon
        duong do do khoi canvas (dong bo 2 chieu: bang <-> canvas)."""
        for row in range(self.table_pinned_points.rowCount()):
            if self.table_pinned_points.cellWidget(row, 3) is btn_remove:
                self.table_pinned_points.removeRow(row)
                break
        self.canvas.remove_saved_measure_line(line_id)
        self._update_pinned_panel_visibility()

    def _clear_pinned_points(self):
        self.table_pinned_points.setRowCount(0)
        self.canvas.clear_all_saved_measure_lines()
        self._update_pinned_panel_visibility()

    def _update_pinned_panel_visibility(self):
        """An hoan toan panel "Duong do da luu" (khong chiem khong gian gi)
        khi bang rong - chi hien khi co it nhat 1 duong do da luu."""
        self.pinned_panel.setVisible(self.table_pinned_points.rowCount() > 0)

    def _insert_coordinate(self, x_mm: float, y_mm: float):
        """Chen toa do vao vi tri con tro hien tai trong editor."""
        nd = self.spin_decimals.value()
        # KHONG con chan chen toa do ngoai phoi nua - nguoi dung duoc tuy bien
        # tu do click ra ngoai vung phoi da khai bao (vd de ve tham/mo rong
        # thu, hoac phoi khai bao chua chinh xac). Xem _is_within_workpiece()
        # neu can bat lai kiem tra nay sau.
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
        insert_start = cursor.position()
        cursor.insertText(snippet)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

        # Ghi nho CHINH XAC vi tri + do dai cua doan vua chen (khong dung
        # editor.undo() chuan cua Qt) - de "hoan tac" (chuot phai tren canvas)
        # chi XOA DUNG PHAN X/Y nay, khong dinh vao cac thao tac go phim khac
        # (vd Qt co the gop lenh Enter tao dong N moi voi lenh chen X Y ngay
        # sau do thanh 1 buoc undo duy nhat neu khong co gi ngat quang giua
        # 2 thao tac, khien "hoan tac" xoa nham ca dong).
        self._last_inserted_coord = (insert_start, len(snippet))

        self.last_ref_point = (x_mm, y_mm)
        self.status.showMessage(
            f"Đã chèn: {snippet}  (click tại X{x_mm:.{nd}f} Y{y_mm:.{nd}f} tuyệt đối) — "
            f"chuột phải trên bản vẽ để hoàn tác"
        )

    def _on_canvas_undo(self):
        if self.chk_measure_mode.isChecked():
            self._measure_first_point = None
            self.canvas.clear_measure_preview()
            self.status.showMessage("Đã huỷ phép đo đang chọn.")
            return

        if self._last_inserted_coord is not None:
            # Xoa DUNG doan X/Y vua chen (theo vi tri + do dai da ghi nho),
            # KHONG dung editor.undo() chuan cua Qt - vi Qt co the gop nham
            # thao tac Enter/tao dong N moi voi lenh chen X/Y ngay sau do
            # thanh 1 buoc undo duy nhat, khien "hoan tac" xoa mat ca dong N
            # thay vi chi xoa toa do vua chen.
            start, length = self._last_inserted_coord
            text = self.editor.toPlainText()
            if 0 <= start and start + length <= len(text):
                cursor = self.editor.textCursor()
                cursor.setPosition(start)
                cursor.setPosition(start + length, cursor.KeepAnchor)
                cursor.removeSelectedText()
                self.editor.setTextCursor(cursor)
                self.editor.setFocus()
                self._last_inserted_coord = None
                self.status.showMessage("Đã xoá tọa độ vừa chèn.")
                return

        self.editor.undo()
        self.status.showMessage("Đã hoàn tác thao tác gần nhất.")

    def _on_canvas_mouse_moved(self, x_mm: float, y_mm: float):
        nd = self.spin_decimals.value()
        self.lbl_mouse_coord.setText(f"X {x_mm:.{nd}f}   Y {y_mm:.{nd}f}")
        if self.chk_measure_mode.isChecked():
            self._on_measure_mouse_moved(x_mm, y_mm)

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

    # ---------------- mo phong mui dao CNC ----------------

    def _build_simulation_trajectory(self, result: ParseResult):
        """Xay dung du lieu quy dao mo phong noi suy theo thoi gian va quang duong."""
        self._sim_trajectory = []
        cum_time = 0.0

        for seg in result.segments:
            if seg.kind == "line":
                length = math.hypot(seg.x1 - seg.x0, seg.y1 - seg.y0)
                sub_pts = [(seg.x0, seg.y0), (seg.x1, seg.y1)]
                r0 = 0.0
                a0 = 0.0
                a1 = 0.0
            else:
                r0 = math.hypot(seg.x0 - seg.cx, seg.y0 - seg.cy)
                a0 = math.atan2(seg.y0 - seg.cy, seg.x0 - seg.cx)
                a1 = math.atan2(seg.y1 - seg.cy, seg.x1 - seg.cx)
                if seg.cw:
                    while a1 >= a0:
                        a1 -= 2 * math.pi
                else:
                    while a1 <= a0:
                        a1 += 2 * math.pi
                sweep = abs(a1 - a0)
                length = r0 * sweep
                sub_pts = arc_to_polyline(seg, max_segments=32)

            if seg.rapid:
                speed_mm_s = 90.0
                duration = max(0.12, length / speed_mm_s)
            else:
                f_rate = seg.feed_rate if seg.feed_rate > 0 else 1200.0
                speed_mm_s = max(15.0, min(65.0, f_rate / 60.0))
                duration = max(0.15, length / speed_mm_s)

            item = {
                "seg": seg,
                "length": length,
                "duration": duration,
                "start_time": cum_time,
                "end_time": cum_time + duration,
                "sub_pts": sub_pts,
                "r0": r0,
                "a0": a0,
                "a1": a1,
            }
            self._sim_trajectory.append(item)
            cum_time += duration

        self._sim_total_duration = cum_time
        if not self._sim_running:
            self._sim_current_time = 0.0
            if self.slider_sim_progress.value() == 0:
                self.canvas.hide_tool()
                self.canvas.clear_sim_trail()

    def _sim_toggle_play(self):
        if not self._sim_trajectory:
            self._render()
            if not self._sim_trajectory:
                self.status.showMessage("Chưa có đường chạy dao để mô phỏng.")
                return

        if self._sim_running:
            self._sim_pause()
        else:
            if self._sim_total_duration > 0 and self._sim_current_time >= self._sim_total_duration - 0.01:
                self._sim_current_time = 0.0
                self.canvas.clear_sim_trail()
            self._sim_play()

    def _sim_play(self):
        self._sim_running = True
        self.btn_sim_play.setText("⏸ Tạm dừng")
        self._sim_timer.start()

    def _sim_pause(self):
        self._sim_running = False
        if self._sim_total_duration > 0 and self._sim_current_time >= self._sim_total_duration - 0.01:
            self.btn_sim_play.setText("▶ Chạy lại")
        else:
            self.btn_sim_play.setText("▶ Tiếp tục")
        self._sim_timer.stop()

    def _sim_stop(self):
        self._sim_pause()
        self._sim_current_time = 0.0
        self.btn_sim_play.setText("▶ Chạy thử")
        self.slider_sim_progress.blockSignals(True)
        self.slider_sim_progress.setValue(0)
        self.slider_sim_progress.blockSignals(False)
        self.canvas.hide_tool()
        self.canvas.clear_sim_trail()
        self._highlight_simulation_line(-1)
        self.lbl_sim_hud.setText("")
        self._last_highlighted_sim_line = None

    def _sim_step_forward(self):
        if not self._sim_trajectory:
            self._render()
            if not self._sim_trajectory:
                return
        self._sim_pause()
        for item in self._sim_trajectory:
            if item["end_time"] > self._sim_current_time + 0.01:
                self._sim_current_time = item["end_time"]
                break
        else:
            self._sim_current_time = self._sim_total_duration
        self._sim_apply_state(self._sim_current_time)

    def _sim_step_backward(self):
        if not self._sim_trajectory:
            return
        self._sim_pause()
        prev_time = 0.0
        for item in self._sim_trajectory:
            if item["start_time"] < self._sim_current_time - 0.05:
                prev_time = item["start_time"]
            else:
                break
        self._sim_current_time = prev_time
        self._sim_apply_state(self._sim_current_time)

    def _sim_on_slider_pressed(self):
        self._sim_is_seeking = True
        self._was_playing_before_seek = self._sim_running
        if self._sim_running:
            self._sim_timer.stop()

    def _sim_on_slider_released(self):
        self._sim_is_seeking = False
        if getattr(self, "_was_playing_before_seek", False):
            self._sim_timer.start()

    def _sim_on_slider_moved(self, val: int):
        if self._sim_total_duration <= 0:
            return
        self._sim_current_time = (val / 1000.0) * self._sim_total_duration
        self._sim_apply_state(self._sim_current_time)

    def _sim_on_speed_changed(self):
        text = self.combo_sim_speed.currentText().replace("x", "")
        try:
            self._sim_speed_multiplier = float(text)
        except ValueError:
            self._sim_speed_multiplier = 1.0

    def _sim_get_state_at_time(self, t_query: float):
        if not self._sim_trajectory:
            return 0.0, 0.0, False, -1, "", []

        t_query = max(0.0, min(self._sim_total_duration, t_query))

        idx = 0
        for i, item in enumerate(self._sim_trajectory):
            if item["start_time"] <= t_query <= item["end_time"]:
                idx = i
                break
            if t_query > item["end_time"]:
                idx = i

        item = self._sim_trajectory[idx]
        seg = item["seg"]
        dur = max(0.0001, item["duration"])
        frac = max(0.0, min(1.0, (t_query - item["start_time"]) / dur))

        if seg.kind == "line":
            x = seg.x0 + frac * (seg.x1 - seg.x0)
            y = seg.y0 + frac * (seg.y1 - seg.y0)
        else:
            angle = item["a0"] + frac * (item["a1"] - item["a0"])
            x = seg.cx + item["r0"] * math.cos(angle)
            y = seg.cy + item["r0"] * math.sin(angle)

        trail_pts = []
        for j in range(idx):
            trail_pts.extend(self._sim_trajectory[j]["sub_pts"])
        if seg.kind == "line":
            trail_pts.append((seg.x0, seg.y0))
            trail_pts.append((x, y))
        else:
            cur_arc_pts = arc_to_polyline(seg, max_segments=32)
            n_samples = max(2, int(len(cur_arc_pts) * frac))
            trail_pts.extend(cur_arc_pts[:n_samples])
            trail_pts.append((x, y))

        status_text = f"[{'G0 Nhanh' if seg.rapid else 'G1 Cắt'}] Dòng {seg.source_line} | X {x:.2f} Y {y:.2f}"
        return x, y, seg.rapid, seg.source_line, status_text, trail_pts

    def _sim_apply_state(self, t: float):
        if not self._sim_trajectory:
            return
        x, y, is_rapid, line_num, hud_text, trail_pts = self._sim_get_state_at_time(t)

        self.canvas.set_tool_position(x, y, is_rapid=is_rapid, visible=True)
        self.canvas.update_sim_trail(trail_pts)
        self.lbl_sim_hud.setText(hud_text)

        if not getattr(self, "_sim_is_seeking", False) and self._sim_total_duration > 0:
            val = int((t / self._sim_total_duration) * 1000)
            self.slider_sim_progress.blockSignals(True)
            self.slider_sim_progress.setValue(val)
            self.slider_sim_progress.blockSignals(False)

        if line_num > 0 and line_num != getattr(self, "_last_highlighted_sim_line", None):
            self._last_highlighted_sim_line = line_num
            self._highlight_simulation_line(line_num)
            self._sync_points_table_row(line_num)

    def _sim_tick(self):
        if not self._sim_running or self._sim_total_duration <= 0:
            return

        dt = 0.033
        self._sim_current_time += dt * self._sim_speed_multiplier

        if self._sim_current_time >= self._sim_total_duration:
            self._sim_current_time = self._sim_total_duration
            self._sim_apply_state(self._sim_current_time)
            self._sim_pause()
            self.lbl_sim_hud.setText("Hoàn thành mô phỏng.")
            self.btn_sim_play.setText("▶ Chạy lại")
            return

        self._sim_apply_state(self._sim_current_time)

    def _highlight_simulation_line(self, line_num: int):
        self.editor.set_simulation_line(line_num)

    def _sync_points_table_row(self, line_num: int):
        self.table_points.blockSignals(True)
        for row in range(self.table_points.rowCount()):
            item = self.table_points.item(row, 0)
            if item:
                src_line, _, _ = item.data(Qt.UserRole)
                if src_line == line_num:
                    self.table_points.selectRow(row)
                    self.table_points.scrollToItem(item)
                    break
        self.table_points.blockSignals(False)

    # ---------------- file I/O ----------------

    def _new_file(self):
        if self.editor.toPlainText().strip():
            reply = QMessageBox.question(
                self, "Tạo mới",
                "Nội dung hiện tại chưa được lưu sẽ mất. Vẫn tạo chương trình mới?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self._sim_stop()
        mode_line = "G90" if self.absolute_mode else "G91"
        self.editor.setPlainText(mode_line + "\n")
        self.last_ref_point = (0.0, 0.0)
        self._last_inserted_coord = None
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
        self._sim_stop()
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
            self._current_file_path = path
            self._last_inserted_coord = None
            self._mark_clean()
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể mở file: {e}")

    def _save_file(self) -> bool:
        """Luu chuong trinh G-code ra file, tra ve True neu luu THANH CONG
        (de closeEvent biet co the thoat duoc khong), False neu nguoi dung
        huy hop thoai hoac gap loi."""
        # KHONG con hoi canh bao truoc khi luu nua (diem ngoai phoi/trung lap)
        # - luu thang, xem _confirm_save_warnings() neu can bat lai sau.
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
    if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QApplication(sys.argv)
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
