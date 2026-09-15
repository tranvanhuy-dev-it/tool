"""
Thuoc do thuong truc (giong Word/Illustrator): 2 thanh doc theo canh TREN va
canh TRAI cua canvas chinh, LUON HIEN THI (khong can bam nut de bat/tat),
dong bo voi zoom/pan THAT cua CanvasWidget qua tin hieu view_changed.

Dung de HIEU CHINH calibration piecewise: nguoi dung double-click tren thuoc
de them 1 vach chia (tai vi tri pixel ANH GOC tuong ung diem do), keo vach de
doi vi tri, click vao 1 vach de mo popup nho nhap do dai that (mm) cho doan
ke ben - moi thay doi AP DUNG NGAY LAP TUC vao CanvasWidget (khong can nut
"Ap dung" rieng).

Vach chia luu theo PIXEL ANH GOC (dong bo voi vi tri/kich thuoc anh dang
hien tren canvas), khong phai theo mm da tinh san - tranh vong lap nguoc
(sua calibration dung chinh gia tri no dang tinh ra).

Khong dung AI/ML: toan bo la ve hinh (QPainter) va xu ly chuot thuan tuy.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton, QApplication
from PyQt5.QtGui import QPainter, QPen, QColor, QMouseEvent, QKeySequence
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal, QTimer

RULER_THICKNESS = 26
HANDLE_HIT_PX = 14  # ban kinh vung bam de KEO 1 vach chia (rong hon nhieu so voi chinh cham tron 8px hien thi, de bam trung de dang bang chuot that)


class _MmInputPopup(QWidget):
    """Popup nho, noi len tren canvas, de nhap do dai (mm) cho 1 doan giua 2
    vach chia. Tu dong dong khi mat focus hoac nguoi dung nhan Enter/Esc."""

    value_confirmed = pyqtSignal(float)

    def __init__(self, parent, initial_mm: float, segment_label: str):
        super().__init__(parent, Qt.Popup)
        self.setAttribute(Qt.WA_DeleteOnClose)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(QLabel(segment_label))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(0.001, 1_000_000)
        self.spin.setDecimals(3)
        self.spin.setValue(initial_mm)
        self.spin.setSuffix(" mm")
        self.spin.setMinimumWidth(100)
        layout.addWidget(self.spin)
        btn_ok = QPushButton("OK")
        btn_ok.setFixedWidth(36)
        layout.addWidget(btn_ok)
        btn_ok.clicked.connect(self._confirm)
        self.spin.selectAll()
        self.spin.setFocus()

    def _confirm(self):
        self.value_confirmed.emit(self.spin.value())
        self.close()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._confirm()
        elif event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class RulerWidget(QWidget):
    """1 thanh thuoc (ngang hoac doc), LUON HIEN, dong bo voi canvas that qua
    view_changed. axis: 'x' (ngang, tren canvas) hoac 'y' (doc, ben trai)."""

    # phat khi nguoi dung xac nhan mm cho 1 doan - main_window lang nghe de
    # goi canvas.set_axis_calibration() ngay lap tuc.
    calibration_changed = pyqtSignal(str, list, list)  # axis, pixel_positions, mm_positions

    def __init__(self, axis: str, canvas, parent=None):
        super().__init__(parent)
        self.axis = axis  # "x" hoac "y"
        self.canvas = canvas
        self._dragging_index = None
        self._pending_popup_token = 0  # tang moi lan huy 1 popup dang cho (xem mouseDoubleClickEvent)
        self._img_w = 1.0
        self._img_h = 1.0

        # breakpoints & mm_lengths: trang thai calibration HIEN TAI cua truc nay,
        # dong bo 2 chieu voi canvas (doc luc load anh, ghi luc nguoi dung sua).
        self._breakpoints_img = [0.0, 1.0]
        self._mm_cumulative = [0.0, 1.0]
        self._label_rects = []  # [(seg_idx, QRect)] cap nhat moi lan paintEvent
        # _fixed_mm[i] = True neu breakpoint thu i (0-based, TRU diem dau=0 va
        # diem cuoi=tong phoi, 2 diem nay luon "co dinh" theo nghia khac) DA
        # duoc nguoi dung TU TAY xac nhan qua popup - dung de biet doan nao
        # "con tu do" (chua chot) khi can don delta vao, tranh de/ghi lai mm
        # cua 1 doan nguoi dung DA nhap truoc do.
        self._fixed_mm = [True, True]

        # Lich su hoan tac (Ctrl+Z): moi phan tu la 1 snapshot (breakpoints, mm)
        # TRUOC khi 1 thay doi duoc ap dung - Ctrl+Z se pop snapshot gan nhat va
        # khoi phuc lai. KHONG ghi lich su khi load_calibration() duoc goi tu
        # ben ngoai (dong bo ban dau/khi tai anh), chi ghi khi CHINH NGUOI DUNG
        # thay doi qua keo/nhap mm/them vach tren thuoc nay.
        self._undo_stack = []
        self.setFocusPolicy(Qt.StrongFocus)  # de nhan duoc phim tat Ctrl+Z khi thuoc dang focus

        if axis == "x":
            self.setFixedHeight(RULER_THICKNESS)
        else:
            self.setFixedWidth(RULER_THICKNESS)

        self.setMouseTracking(True)
        self.canvas.view_changed.connect(self.update)

    def set_image_size(self, img_w: float, img_h: float):
        self._img_w = max(1.0, img_w)
        self._img_h = max(1.0, img_h)

    def load_calibration(self, pixel_positions: list, mm_positions: list):
        self._breakpoints_img = list(pixel_positions)
        self._mm_cumulative = list(mm_positions)
        if len(self._fixed_mm) != len(self._breakpoints_img):
            self._fixed_mm = [True] * len(self._breakpoints_img)
        self.update()

    # ---------- quy doi pixel ANH GOC <-> vi tri MAN HINH tren thuoc ----------
    # Dung dung transform THAT cua canvas (mm_to_scene + mapFromScene) de dam
    # bao dong bo tuyet doi voi zoom/pan hien tai, khong tu tinh scale rieng.

    def _img_px_to_screen(self, img_px: float) -> float:
        """img_px: vi tri PIXEL ANH GOC (0 = canh dau truc, kieu QPixmap: X tu
        trai, Y tu tren). Tra ve toa do MAN HINH (px) tren thuoc nay.

        QUAN TRONG: dung image_px_to_display_mm() (ty le CO DINH theo Rong/Cao
        phoi), KHONG dung image_px_to_mm() (calibration piecewise) - neu khong
        vi tri VE cua vach se bi tinh lai va "nhay"/"co lai" moi khi nguoi dung
        sua gia tri mm cua BAT KY doan nao (ke ca doan khac vach dang xem), du
        khong he keo gi ca. Vach phai LUON dung yen tai dung pixel ban da dat,
        chi doi khi CHINH BAN KEO no."""
        if self.axis == "x":
            x_mm, _ = self.canvas.image_px_to_display_mm(img_px, 0)
            scene_pt = self.canvas.mm_to_scene(x_mm, 0)
            view_pt = self.canvas.mapFromScene(scene_pt)
            return view_pt.x()
        else:
            _, y_mm = self.canvas.image_px_to_display_mm(0, img_px)
            scene_pt = self.canvas.mm_to_scene(0, y_mm)
            view_pt = self.canvas.mapFromScene(scene_pt)
            return view_pt.y()

    def _screen_to_img_px(self, screen_px: float) -> float:
        """Chieu nguoc: tu vi tri MAN HINH tren thuoc ra PIXEL ANH GOC, dung
        DUNG ty le hien thi CO DINH (khop voi _img_px_to_screen o tren) - de
        khi KEO vach, vi tri moi tinh dung theo pixel anh dang nhin thay,
        khong bi lech boi calibration piecewise cua cac doan khac."""
        ax, ay = self.canvas._offset_a_mm
        sx, sy = self.canvas._px_per_mm_xy()
        if self.axis == "x":
            scene_pt = self.canvas.mapToScene(int(screen_px), 0)
            x_mm, _ = self.canvas.scene_to_mm(scene_pt)
            return (x_mm - ax) * sx
        else:
            scene_pt = self.canvas.mapToScene(0, int(screen_px))
            _, y_mm = self.canvas.scene_to_mm(scene_pt)
            img_px_from_bottom = (y_mm - ay) * sy
            return self._img_h - img_px_from_bottom

    # ---------- ve ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Nen TRANG, giong nen cua vung ve (canvas) chinh - de thuoc trong lien
        # mach voi ban ve, khong noi bat mot mau nen rieng.
        painter.fillRect(self.rect(), QColor("#ffffff"))

        pen_tick = QPen(QColor("#9ca3af"), 1)
        pen_handle = QPen(QColor("#3b9eff"), 2)
        brush_handle = QColor("#3b9eff")

        # cac vach mm nho (moi 10mm) de tham khao, kieu thuoc ke that
        painter.setPen(pen_tick)
        self._draw_minor_ticks(painter)

        # cac vach chia calibration (keo duoc)
        for bp in self._breakpoints_img:
            pos = self._img_px_to_screen(bp)
            painter.setPen(pen_handle)
            painter.setBrush(brush_handle)
            if self.axis == "x":
                painter.drawLine(int(pos), 0, int(pos), self.height())
                painter.drawEllipse(int(pos) - 4, self.height() - 9, 8, 8)
            else:
                painter.drawLine(0, int(pos), self.width(), int(pos))
                painter.drawEllipse(self.width() - 9, int(pos) - 4, 8, 8)

        self._draw_segment_labels(painter)

    def _draw_segment_labels(self, painter: QPainter):
        """Hien do dai (mm) HIEN TAI cua tung doan ngay giua than doan do tren
        thuoc - de nguoi dung theo doi ngay lap tuc, dac biet la doan CUOI CUNG
        (chua nhap/chi con lai) vi do dai cua no LUON tu dong = tong phoi TRU
        di tong cac doan da nhap truoc do (do _mm_cumulative[-1] la moc co
        dinh = tong do dai truc), khong can tinh tay. Cung luu lai VUNG HINH
        CHU NHAT cua tung nhan (self._label_rects) de mousePressEvent biet
        nguoi dung co click DUNG vao con so hay khong (chi noi nay moi mo
        duoc popup sua, khong phai bat ky dau tren than doan)."""
        painter.setPen(QColor("#1e293b"))
        font = painter.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        painter.setFont(font)
        bps = self._breakpoints_img
        n = len(bps)
        self._label_rects = []  # list[(seg_idx, QRect)] - toa do MAN HINH cua thuoc nay
        for i in range(n - 1):
            seg_mm = self._mm_cumulative[i + 1] - self._mm_cumulative[i]
            p0 = self._img_px_to_screen(bps[i])
            p1 = self._img_px_to_screen(bps[i + 1])
            mid = (p0 + p1) / 2.0
            text = f"{seg_mm:.2f}"
            if self.axis == "x":
                rect_w = max(30, abs(p1 - p0))
                rect = QRect(int(mid - rect_w / 2), 0, int(rect_w), self.height() - 10)
                painter.drawText(rect, Qt.AlignHCenter | Qt.AlignVCenter, text)
                self._label_rects.append((i, rect))
            else:
                rect_h = max(16, abs(p1 - p0))
                painter.save()
                painter.translate(self.width() - 10, int(mid))
                painter.rotate(-90)
                local_rect = QRect(int(-rect_h / 2), -12, int(rect_h), 12)
                painter.drawText(local_rect, Qt.AlignHCenter | Qt.AlignVCenter, text)
                painter.restore()
                # vung click phai tinh theo toa do MAN HINH THAT (chua xoay) de
                # mousePressEvent so sanh duoc: 1 dai ngang mong quanh vi tri mid
                # tren truc doc (vi nhan da xoay -90 do de doc theo thuoc Y).
                screen_rect = QRect(self.width() - 22, int(mid - rect_h / 2), 16, int(rect_h))
                self._label_rects.append((i, screen_rect))

    def _draw_minor_ticks(self, painter: QPainter):
        """Ve vach mm nho moi 10mm trong pham vi dang hien thi, chi de tham
        khao truc quan (giong thuoc ke Word), khong tuong tac duoc."""
        if self.axis == "x":
            top_left_mm, _ = self.canvas.scene_to_mm(self.canvas.mapToScene(0, 0))
            bottom_right_mm, _ = self.canvas.scene_to_mm(self.canvas.mapToScene(self.width(), 0))
            lo, hi = sorted((top_left_mm, bottom_right_mm))
        else:
            _, top_mm = self.canvas.scene_to_mm(self.canvas.mapToScene(0, 0))
            _, bottom_mm = self.canvas.scene_to_mm(self.canvas.mapToScene(0, self.height()))
            lo, hi = sorted((top_mm, bottom_mm))

        if hi - lo > 2000 or hi <= lo:
            return  # zoom qua nho, qua nhieu vach -> bo qua de tranh treo UI

        import math
        step = 10.0
        start = math.floor(lo / step) * step
        mm = start
        while mm <= hi:
            if self.axis == "x":
                scene_pt = self.canvas.mm_to_scene(mm, 0)
                pos = self.canvas.mapFromScene(scene_pt).x()
                painter.drawLine(int(pos), self.height() - 5, int(pos), self.height())
            else:
                scene_pt = self.canvas.mm_to_scene(0, mm)
                pos = self.canvas.mapFromScene(scene_pt).y()
                painter.drawLine(self.width() - 5, int(pos), self.width(), int(pos))
            mm += step

    # ---------- tuong tac chuot ----------

    def _pos_from_event(self, event: QMouseEvent) -> float:
        return event.pos().x() if self.axis == "x" else event.pos().y()

    def _find_nearby_breakpoint(self, screen_pos: float):
        for i, bp in enumerate(self._breakpoints_img):
            if abs(self._img_px_to_screen(bp) - screen_pos) <= HANDLE_HIT_PX:
                return i
        return None

    def _find_label_at(self, event_pos: QPoint):
        """Tim doan (0-based) ma NHAN SO MM cua no dang chua diem click nay -
        CHI khi click DUNG vao con so (khong phai bat ky dau tren than doan)
        moi duoc mo popup sua gia tri, theo dung yeu cau: tranh nguoi dung vo
        tinh mo popup khi chi dinh click de xem/di chuyen."""
        for seg_idx, rect in self._label_rects:
            if rect.contains(event_pos):
                return seg_idx
        return None

    def _has_valid_image(self) -> bool:
        """True neu canvas da co anh nen that su (khong phai gia tri mac dinh
        1.0x1.0 luc chua tai anh nao). Chan thao tac them/keo vach khi chua
        co anh - neu khong, _breakpoints_img se van nam trong thang do mac
        dinh [0,1] (chua tung duoc load_calibration() voi du lieu that), gay
        loi tinh toan lo > hi trong mouseMoveEvent (vd lo=1.0, hi=0.0), khien
        vach bi ep cung ve 1 dau moi lan keo thay vi di chuyen binh thuong."""
        return getattr(self.canvas, "_bg_image_path", None) is not None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        if not self._has_valid_image():
            return
        # Nhan focus ve THUOC nay khi nguoi dung tuong tac, de phim tat Ctrl+Z
        # (bat trong keyPressEvent) hoat dong dung tren truc vua duoc sua, thay
        # vi bi editor G-code hoac widget khac "cuop" phim tat.
        self.setFocus()
        pos = self._pos_from_event(event)
        idx = self._find_nearby_breakpoint(pos)
        if idx is not None and idx not in (0, len(self._breakpoints_img) - 1):
            # Trung dung 1 HANDLE (vach giua, khong phai dau/cuoi co dinh) ->
            # bat dau KEO ngay, KHONG mo popup. Luu snapshot TRUOC khi keo lam
            # thay doi vi tri, de Ctrl+Z co the khoi phuc lai dung vi tri cu.
            self._push_undo_snapshot()
            self._dragging_index = idx
            return

        if idx is None:
            # Khong trung handle nao -> kiem tra co click DUNG VAO CON SO (nhan
            # mm) cua 1 doan khong - CHI noi nay moi duoc mo popup sua, click o
            # bat ky cho nao khac tren than doan se KHONG lam gi ca (tranh mo
            # popup ngoai y muon). KHONG mo popup NGAY: Qt luon phat
            # mousePressEvent truoc ca khi nguoi dung dang double-click, nen
            # phai TRI HOAN bang doubleClickInterval() - neu mouseDoubleClickEvent
            # den truoc khi het gio, huy popup (xem _pending_popup_token).
            seg_idx = self._find_label_at(event.pos())
            if seg_idx is not None:
                self._pending_popup_token += 1
                token = self._pending_popup_token
                global_pos = event.globalPos()
                interval = QApplication.doubleClickInterval()
                QTimer.singleShot(
                    interval,
                    lambda: self._maybe_open_popup(token, seg_idx, global_pos),
                )

    def _maybe_open_popup(self, token: int, seg_idx: int, global_pos: QPoint):
        """Chi thuc su mo popup neu KHONG co double-click nao xay ra trong
        luc cho (token con khop nghia la chua bi mouseDoubleClickEvent huy)."""
        if token == self._pending_popup_token:
            self._open_mm_popup_for_segment(seg_idx, global_pos)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging_index is None:
            return
        pos = self._pos_from_event(event)
        new_img_pos = self._screen_to_img_px(pos)
        idx = self._dragging_index
        if idx in (0, len(self._breakpoints_img) - 1):
            self._dragging_index = None  # vach dau/cuoi co dinh, khong keo duoc
            return
        lo = self._breakpoints_img[idx - 1] + 1
        hi = self._breakpoints_img[idx + 1] - 1
        new_img_pos = max(lo, min(hi, new_img_pos))
        self._breakpoints_img[idx] = new_img_pos
        self.update()

        # Ve duong ke huong dan XUYEN SUOT ban ve tai vi tri dang keo, de nguoi
        # dung can chinh chinh xac theo chi tiet trong anh nen. Dung
        # image_px_to_display_mm() (ty le CO DINH) de guide line khop DUNG voi
        # vi tri hien thi cua anh, khong bi anh huong boi calibration piecewise.
        if self.axis == "x":
            mm_pos, _ = self.canvas.image_px_to_display_mm(new_img_pos, 0)
        else:
            _, mm_pos = self.canvas.image_px_to_display_mm(0, new_img_pos)
        self.canvas.show_guide_line(self.axis, mm_pos)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.canvas.clear_guide_line()
        if self._dragging_index is None:
            return
        self._dragging_index = None
        # Da keo xong -> ap dung calibration ngay voi vi tri moi (khong mo
        # popup, dung y nguoi dung da chon xong vi tri bang mat qua guide line).
        self._emit_calibration()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if not self._has_valid_image():
            return
        # Huy MOI popup dang cho tu mousePressEvent truoc do (chinh la cai press
        # dau tien cua cu double-click nay) - tang token de _maybe_open_popup()
        # tu bien mat khi timer no.
        self._pending_popup_token += 1

        pos = self._pos_from_event(event)
        new_img_pos = self._screen_to_img_px(pos)
        total = self._breakpoints_img[-1]
        for bp in self._breakpoints_img:
            if abs(bp - new_img_pos) < total * 0.01:
                return
        self._push_undo_snapshot()  # luu truoc khi them vach moi, de Ctrl+Z go duoc
        self._insert_breakpoint(new_img_pos)
        self.update()
        # KHONG tu dong mo popup nhap mm o day nua - chi them vach chia moi.
        # Nguoi dung muon nhap do dai thi PHAI click DUNG VAO CON SO nhan (xem
        # _find_label_at/_open_mm_popup_for_segment), giong het cach sua mm
        # cho 1 doan da co san - nhat quan cho moi truong hop, tranh popup tu
        # bat len ngoai y muon ngay khi vua them vach.

    def _insert_breakpoint(self, new_img_pos: float):
        """Them 1 vach chia moi tai new_img_pos, CHI noi suy mm TAM THOI cho
        vi tri moi nay bang ty le pixel CUC BO trong dung doan cu chua no -
        KHONG dong lai toan bo danh sach mm theo tong (khac _resync_mm_length
        cu, vi cach do se GHI DE len cac gia tri mm nguoi dung DA NHAP TAY cho
        cac doan khac, gay loi "doan cu tu doi gia tri" khi them vach moi)."""
        bps = self._breakpoints_img
        mms = self._mm_cumulative
        # tim doan cu (i, i+1) chua new_img_pos
        i = 0
        for k in range(len(bps) - 1):
            if bps[k] <= new_img_pos <= bps[k + 1]:
                i = k
                break
        px0, px1 = bps[i], bps[i + 1]
        mm0, mm1 = mms[i], mms[i + 1]
        span_px = px1 - px0
        t = (new_img_pos - px0) / span_px if abs(span_px) > 1e-9 else 0.5
        new_mm = mm0 + t * (mm1 - mm0)
        bps.insert(i + 1, new_img_pos)
        mms.insert(i + 1, new_mm)
        # vach moi CHUA duoc nguoi dung xac nhan mm rieng (chi la noi suy tam),
        # nen danh dau CHUA CHOT - se duoc chot that khi ho nhap qua popup.
        self._fixed_mm.insert(i + 1, False)

    def _open_mm_popup_for_segment(self, seg_idx: int, global_pos: QPoint):
        """Mo popup nhap mm cho DUNG doan co chi so seg_idx - dung khi nguoi
        dung click truc tiep vao THAN mot doan tren thuoc (khong trung handle)."""
        current_mm = self._mm_cumulative[seg_idx + 1] - self._mm_cumulative[seg_idx]
        label = f"Đoạn {seg_idx + 1}:"
        popup = _MmInputPopup(self, current_mm, label)
        popup.value_confirmed.connect(lambda v: self._on_mm_confirmed(seg_idx, v))
        popup.move(global_pos)
        popup.show()

    def _on_mm_confirmed(self, seg_idx: int, mm_value: float):
        """Ap dung gia tri mm nguoi dung vua nhap cho DUNG 1 doan (seg_idx),
        theo nguyen tac: KHONG BAO GIO tu y sua mm cua bat ky doan nao KHAC
        DA duoc chot truoc do. Vach dau doan (seg_idx) luon giu nguyen (no la
        ranh gioi voi doan truoc). Phan chenh lech (delta) duoc don vao vach
        CUOI doan (seg_idx+1) NEU vach do CHUA bi chot boi 1 gia tri khac -
        tuc la doan ke tiep con dang la "phan con lai tu do", se tu dong co
        gian de bu (dung y "tinh toan hop ly", khong pha vo doan da chot).
        Neu vach cuoi doan DA bi chot (nghia la moi doan phia sau no toi tan
        cuoi truc deu da co gia tri co dinh, khong con doan tu do nao de bu)
        thi KHONG THE ap dung ma khong lam sai 1 doan da chot khac - bao loi
        cho nguoi dung biet thay vi am tham ghi de."""
        old_len = self._mm_cumulative[seg_idx + 1] - self._mm_cumulative[seg_idx]
        delta = mm_value - old_len
        if abs(delta) < 1e-9:
            return  # gia tri khong doi, khong can luu lich su/ap dung lai

        end_idx = seg_idx + 1
        last_idx = len(self._mm_cumulative) - 1
        if end_idx != last_idx and self._fixed_mm[end_idx]:
            # Vach cuoi doan nay DA duoc chot (co doan khac dang dua vao no) ->
            # khong con "phan tu do" ngay ke ben de hap thu chenh lech. Tu choi
            # thay vi lam sai doan da chot khac.
            from PyQt5.QtWidgets import QToolTip
            QToolTip.showText(self.mapToGlobal(QPoint(0, 0)),
                               "Không thể sửa: đoạn kế tiếp đã được cố định.\n"
                               "Hãy sửa đoạn liền sau trước, hoặc xoá vạch chia đó.")
            return

        self._push_undo_snapshot()
        self._mm_cumulative[end_idx] += delta
        # Doan nay gio da duoc nguoi dung TU TAY chot - vach cuoi cua no
        # (end_idx) danh dau la CO DINH, tru khi no chinh la moc cuoi cung
        # (tong phoi) - moc do luon duoc coi la "co dinh" theo nghia rieng,
        # khong can flag, va KHONG bao gio la "phan tu do" de doan sau dua vao
        # (vi khong con doan nao sau no).
        if end_idx != last_idx:
            self._fixed_mm[end_idx] = True
        self._emit_calibration()
        self.update()

    def _emit_calibration(self):
        self.calibration_changed.emit(self.axis, list(self._breakpoints_img), list(self._mm_cumulative))

    # ---------- hoan tac (Ctrl+Z) ----------

    _UNDO_STACK_MAX = 50

    def _push_undo_snapshot(self):
        """Luu lai trang thai HIEN TAI (truoc khi ap dung 1 thay doi moi) vao
        lich su hoan tac. Goi ngay TRUOC moi mutation thuc su (keo xong, them
        vach, doi mm) - khong goi khi chi dong bo tu ben ngoai (load_calibration)."""
        self._undo_stack.append(
            (list(self._breakpoints_img), list(self._mm_cumulative), list(self._fixed_mm))
        )
        if len(self._undo_stack) > self._UNDO_STACK_MAX:
            self._undo_stack.pop(0)

    def undo(self) -> bool:
        """Khoi phuc snapshot gan nhat trong lich su. Tra ve True neu co gi
        de hoan tac (va da ap dung), False neu lich su rong."""
        if not self._undo_stack:
            return False
        self._breakpoints_img, self._mm_cumulative, self._fixed_mm = self._undo_stack.pop()
        self.update()
        self._emit_calibration()
        return True

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Undo):
            self.undo()
            event.accept()
            return
        super().keyPressEvent(event)
