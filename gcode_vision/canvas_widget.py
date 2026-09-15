"""
Vung ve (canvas) hien thi duong chay dao CNC.

Khong dung AI/ML: toan bo la hinh hoc thuan tuy (QPainter ve line/arc da duoc
roi rac hoa thanh polyline boi gcode_parser.arc_to_polyline).

He quy chieu: goc (0,0) o GOC DUOI TRAI cua vung ve, truc X sang phai,
truc Y huong LEN (giong ban ve co khi / CNC thuc te), khac voi he toa do
man hinh mac dinh cua Qt (goc tren trai, Y huong xuong) -> can quy doi.
"""

from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsItem,
)
from PyQt5.QtGui import QPen, QColor, QBrush, QPainter, QFont, QPixmap
from PyQt5.QtCore import Qt, QPointF, pyqtSignal, QRectF

from gcode_vision.gcode_parser import ParseResult, Segment, arc_to_polyline
from gcode_vision.ruler_calibration import AxisCalibration

MM_TO_PX = 4.0          # ty le hien thi: 1 mm ban ve = 4 px man hinh
MARGIN_PX = 40           # le trang de con hien thi truc va nhan toa do


class CanvasWidget(QGraphicsView):
    # phat tin hieu khi nguoi dung click vao ban ve: toa do (mm) trong he tuyet doi
    point_clicked = pyqtSignal(float, float)
    # phat tin hieu khi nguoi dung click CHUOT PHAI: yeu cau hoan tac thao tac gan nhat
    undo_requested = pyqtSignal()
    # phat tin hieu lien tuc khi di chuyen chuot tren canvas: toa do (mm), da snap luoi neu du gan
    mouse_moved_mm = pyqtSignal(float, float)
    # phat tin hieu moi khi zoom/pan/resize thay doi (transform hoac scrollbar) - de
    # cac widget thuoc do (RulerWidget) ben ngoai tu ve lai cho dong bo voi canvas.
    view_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor("#ffffff"))
        # zoom bang cuon chuot se lay TAM la vi tri con tro, khong phai tam khung nhin
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        self._last_click_mm = None   # diem click gan nhat, dung cho toa do tuong doi
        self._known_points_mm: list[tuple[float, float]] = []  # cac diem X/Y (mm THAT) da co trong G-code, de snap vao
        self._origin_px = QPointF(MARGIN_PX, 0)  # cap nhat khi resize/draw
        self._segments: list[Segment] = []
        self._has_fitted_once = False  # chi tu dong fitInView() o lan render dau tien
        self._user_has_zoomed = False  # danh dau nguoi dung da tu thu phong/di chuyen

        self._colors = dict(
            cut="#1e293b", rapid="#94a3b8", axis="#ef4444",
            grid="#e5e7eb", hover="#3b9eff",
        )
        self._pen_cut = QPen(QColor(self._colors["cut"]), 1.4)
        self._pen_rapid = QPen(QColor(self._colors["rapid"]), 1.0, Qt.DashLine)
        self._pen_axis = QPen(QColor(self._colors["axis"]), 1.2)
        self._pen_grid = QPen(QColor(self._colors["grid"]), 0.6)

        self._hover_marker_items: list = []  # vong tron + 2 duong crosshair khi hover gan giao diem luoi
        self._press_pos = None    # vi tri bat dau nhan chuot trai, de phan biet click voi keo
        self._last_drag_pos = None
        self._is_dragging = False
        self._pen_hover_line = QPen(QColor(self._colors["hover"]), 1.2, Qt.DashLine)
        self._last_grid_bounds = (0.0, 0.0, 0.0, 0.0)  # min_x,max_x,min_y,max_y cua luoi hien tai
        self._guide_line_item = None  # duong ke tam thoi khi keo vach chia tren thuoc do
        self._measure_line_item = None  # doan thang tam thoi cua cong cu do khoang cach
        self._measure_dot_items: list = []

        # --- anh nen (ban ve tham chieu, da duoc crop khop khung phoi) ---
        # Quy uoc: goc DUOI-TRAI cua anh (pixel (0, image_height)) la moc tham chieu.
        # Kich thuoc phoi thuc te (mm) chia cho kich thuoc anh (px) -> ty le rieng cho X va Y
        # (khong bat buoc vuong, phong truong hop anh chup/scan bi meo nhe theo 1 chieu).
        # Toa do gia cong that = quy doi theo ty le do, roi CONG THEM offset (a_x, a_y).
        self._bg_pixmap_item: QGraphicsPixmapItem | None = None
        self._bg_image_path: str | None = None
        self._bg_source_pixmap: QPixmap | None = None
        self._bg_image_w_px = 1.0
        self._bg_image_h_px = 1.0
        self._workpiece_w_mm = 100.0
        self._workpiece_h_mm = 100.0
        self._offset_a_mm = (0.0, 0.0)

        # Hieu chuan ty le px/mm THEO TUNG DOAN (piecewise), rieng cho truc X va Y.
        # Mac dinh (chua hieu chuan chi tiet) chi co 1 doan duy nhat, tuong duong
        # dung Rong/Cao phoi nhu truoc - xem set_workpiece_size() va _sync_default_calibration().
        self._calib_x = AxisCalibration()
        self._calib_y = AxisCalibration()
        self._bg_opacity = 0.5
        self._grid_step_mm = 5.0
        self._snap_enabled = True
        self._snap_radius_px = 10.0  # ban kinh hut luoi, tinh theo PIXEL MAN HINH (khong doi theo zoom)
        self._marker_radius_px = 9.0  # ban kinh vong tron danh dau diem giao khi hover, tinh theo PIXEL MAN HINH

    # ---------- anh nen ----------

    def clear_background_image(self):
        if self._bg_pixmap_item is not None:
            self.scene.removeItem(self._bg_pixmap_item)
            self._bg_pixmap_item = None
        self._bg_image_path = None
        self._bg_source_pixmap = None
        self._bg_image_w_px = 1.0
        self._bg_image_h_px = 1.0

    def set_background_image(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            raise ValueError(f"Khong the nap anh: {path}")
        self._bg_image_path = path
        self._bg_source_pixmap = pix
        self._bg_image_w_px = float(pix.width())
        self._bg_image_h_px = float(pix.height())
        self._sync_default_calibration()
        self._redraw_background()
        # Anh moi co the co kich thuoc rat khac voi khung nhin dang fit hien tai
        # (vd luc khoi dong dang fit theo vung 200x200mm mac dinh) - danh dau
        # can fit lai NGAY LAN render tiep theo, tranh anh hien qua nho/lon sai
        # ty le so voi khung nhin (chinh la nguyen nhan gay cam giac "thuoc bi lech").
        self._has_fitted_once = False
        self._user_has_zoomed = False

    def set_background_opacity(self, value: float):
        self._bg_opacity = max(0.0, min(1.0, value))
        if self._bg_pixmap_item:
            self._bg_pixmap_item.setOpacity(self._bg_opacity)

    def set_workpiece_size(self, width_mm: float, height_mm: float):
        """Kich thuoc THUC TE (mm) cua phoi, tuong ung voi toan bo chieu rong/cao
        cua anh da crop. Dung lam ty le mac dinh (1 doan don gian) cho ca truc X,
        Y - bi ghi de neu nguoi dung da hieu chuan chi tiet bang thuoc do (xem
        set_axis_calibration)."""
        self._workpiece_w_mm = max(1e-6, width_mm)
        self._workpiece_h_mm = max(1e-6, height_mm)
        self._sync_default_calibration()
        self._redraw_background()

    def set_offset_a(self, a_x_mm: float, a_y_mm: float):
        """Tham so 'a': do lech (mm) tu goc DUOI-TRAI cua anh den goc toa do
        gia cong that (0,0) ma may CNC se dung. Nguoi dung chinh tuy y."""
        self._offset_a_mm = (a_x_mm, a_y_mm)
        self._redraw_background()

    def _sync_default_calibration(self):
        """Cap nhat lai calibration mac dinh (1 doan) tu Rong/Cao phoi - CHI khi
        nguoi dung CHUA tu hieu chuan chi tiet bang thuoc do (is_default() == True),
        de khong ghi de mat cong suc hieu chuan da lam."""
        if self._calib_x.is_default():
            self._calib_x.set_from_total(self._bg_image_w_px, self._workpiece_w_mm)
        if self._calib_y.is_default():
            self._calib_y.set_from_total(self._bg_image_h_px, self._workpiece_h_mm)

    def set_axis_calibration(self, axis: str, pixel_positions: list, mm_positions: list):
        """Thiet lap hieu chuan CHI TIET (nhieu doan) cho 1 truc, tu ket qua
        nguoi dung keo tren thuoc do overlay. axis: 'x' hoac 'y'."""
        calib = self._calib_x if axis == "x" else self._calib_y
        calib.set_breakpoints(pixel_positions, mm_positions)
        self._redraw_background()

    def reset_axis_calibration(self, axis: str = None):
        """Xoa hieu chuan chi tiet, quay ve dung 1 ty le don gian tu Rong/Cao phoi.
        axis=None: reset ca 2 truc."""
        if axis in (None, "x"):
            self._calib_x = AxisCalibration()
        if axis in (None, "y"):
            self._calib_y = AxisCalibration()
        self._sync_default_calibration()
        self._redraw_background()

    def _px_per_mm_xy(self) -> tuple[float, float]:
        """Ty le hien thi CO DINH, dung DUNG Rong/Cao phoi nguoi dung nhap (KHONG
        phu thuoc calibration piecewise chi tiet) - de anh nen LUON hien thi
        dung 1 kich thuoc co dinh, khong bi co gian/meo moi khi nguoi dung sua
        mm cho 1 doan tren thuoc do. Tinh toa do click van dung image_px_to_mm()
        voi calibration piecewise chinh xac, chi rieng phan VE anh la co dinh."""
        sx = self._bg_image_w_px / max(1e-9, self._workpiece_w_mm)
        sy = self._bg_image_h_px / max(1e-9, self._workpiece_h_mm)
        return sx, sy

    def image_px_to_mm(self, ix: float, iy: float) -> tuple[float, float]:
        """Quy doi toa do pixel trong ANH GOC (0,0 tren-trai, Y huong xuong) sang
        toa do gia cong THAT (mm), da cong offset a. Dung hieu chuan PIECEWISE
        (chinh xac theo tung doan da hieu chuan) neu nguoi dung da thiet lap,
        khong chi 1 ty le tuyen tinh don gian cho ca truc. DUNG DE: xuat toa do
        khi click chon diem (gia tri G-code thuc te)."""
        ax, ay = self._offset_a_mm
        x_mm = self._calib_x.pixel_to_mm(ix) + ax
        y_mm = self._calib_y.pixel_to_mm(self._bg_image_h_px - iy) + ay
        return x_mm, y_mm

    def image_px_to_display_mm(self, ix: float, iy: float) -> tuple[float, float]:
        """Quy doi pixel ANH GOC sang mm theo TY LE HIEN THI CO DINH (Rong/Cao
        phoi, KHONG dung calibration piecewise) - dung DE VE (vi tri vach chia
        tren thuoc do, vi tri anh nen tren canvas). Vi tri VE tren man hinh vi
        vay LUON CO DINH theo dung pixel ban da dat/keo, KHONG tu dich chuyen
        moi khi ban sua gia tri mm cua bat ky doan nao khac tren thuoc - chi mm
        HIEN THI (nhan so) thay doi, con VI TRI VE thi khong doi tru khi ban
        chu dong keo lai vach do."""
        ax, ay = self._offset_a_mm
        sx, sy = self._px_per_mm_xy()
        x_mm = ix / sx + ax
        y_mm = (self._bg_image_h_px - iy) / sy + ay
        return x_mm, y_mm

    def _redraw_background(self):
        if self._bg_pixmap_item is not None:
            self.scene.removeItem(self._bg_pixmap_item)
            self._bg_pixmap_item = None
        if self._bg_image_path is None:
            return
        item = QGraphicsPixmapItem(self._bg_source_pixmap)
        sx, sy = self._px_per_mm_xy()
        scale_x = MM_TO_PX / sx
        scale_y = MM_TO_PX / sy
        ax, ay = self._offset_a_mm
        item.setTransform(item.transform().scale(scale_x, scale_y))
        # goc duoi-trai anh (0, h) ung voi mm (ax, ay) -> scene = mm_to_scene(ax, ay)
        origin_scene = self.mm_to_scene(ax, ay)
        item.setPos(origin_scene.x(), origin_scene.y() - self._bg_image_h_px * scale_y)
        item.setOpacity(self._bg_opacity)
        item.setZValue(-100)
        self.scene.addItem(item)
        self._bg_pixmap_item = item

    # ---------- quy doi toa do ----------

    def mm_to_scene(self, x_mm: float, y_mm: float) -> QPointF:
        """Quy doi toa do ban ve (mm, Y huong len) sang toa do scene cua Qt (Y huong xuong)."""
        return QPointF(x_mm * MM_TO_PX, -y_mm * MM_TO_PX)

    def scene_to_mm(self, pt: QPointF) -> tuple[float, float]:
        return (pt.x() / MM_TO_PX, -pt.y() / MM_TO_PX)

    def real_mm_to_scene(self, x_mm: float, y_mm: float) -> QPointF:
        """Chieu NGUOC LAI cua scene_to_real_mm(): tu mm THAT (piecewise, vd so
        X/Y ghi trong G-code) ra diem scene DE VE - di qua pixel ANH GOC de
        diem/duong ve TRUNG KHOP DUNG VI TRI PIXEL tren anh nen (khong bi lech
        do anh co vung ty le khong deu), thay vi mm_to_scene() (chia deu, chi
        dung khi CHUA co anh nen/calibration)."""
        if self._bg_image_path is None:
            return self.mm_to_scene(x_mm, y_mm)
        ax, ay = self._offset_a_mm
        ix = self._calib_x.mm_to_pixel(x_mm - ax)
        iy_from_bottom = self._calib_y.mm_to_pixel(y_mm - ay)
        iy = self._bg_image_h_px - iy_from_bottom
        disp_x_mm, disp_y_mm = self.image_px_to_display_mm(ix, iy)
        return self.mm_to_scene(disp_x_mm, disp_y_mm)

    def scene_to_real_mm(self, pt: QPointF) -> tuple[float, float]:
        """Quy doi 1 diem scene (vi tri click/hover thuc te tren canvas) sang
        toa do gia cong THAT (mm), di qua calibration PIECEWISE neu da co anh
        nen - thay vi chi dung ty le hien thi co dinh (scene_to_mm). Neu chua
        co anh nen thi khong co gi de hieu chuan, tra ve nhu scene_to_mm."""
        if self._bg_image_path is None:
            return self.scene_to_mm(pt)
        display_x_mm, display_y_mm = self.scene_to_mm(pt)
        ax, ay = self._offset_a_mm
        sx, sy = self._px_per_mm_xy()
        # dao nguoc image_px_to_display_mm(): tu display mm ra pixel anh goc
        ix = (display_x_mm - ax) * sx
        iy = self._bg_image_h_px - (display_y_mm - ay) * sy
        return self.image_px_to_mm(ix, iy)

    # ---------- mau sac ----------

    def set_colors(self, cut=None, rapid=None, axis=None, grid=None, hover=None):
        """Doi mau cac loai net ve. Truyen gia tri hex (vd '#ff0000') cho loai can doi,
        bo qua (None) de giu nguyen loai khac."""
        if cut:
            self._colors["cut"] = cut
            self._pen_cut = QPen(QColor(cut), 1.4)
        if rapid:
            self._colors["rapid"] = rapid
            self._pen_rapid = QPen(QColor(rapid), 1.0, Qt.DashLine)
        if axis:
            self._colors["axis"] = axis
            self._pen_axis = QPen(QColor(axis), 1.2)
        if grid:
            self._colors["grid"] = grid
            self._pen_grid = QPen(QColor(grid), 0.6)
        if hover:
            self._colors["hover"] = hover

    def get_colors(self) -> dict:
        return dict(self._colors)

    # ---------- ve lai toan bo ----------

    def fit_view(self):
        """Can lai khung nhin de thay toan bo ban ve va phoi - can vua theo man hinh.
        Co chan tai nhap (re-entrancy guard) vi fitInView() co the tu kich hoat
        resizeEvent noi bo cua Qt, ma resizeEvent lai goi fit_view() -> neu khong
        chan se gay de quy vo han va treo ung dung."""
        if getattr(self, "_in_fit_view", False):
            return
        self._in_fit_view = True
        try:
            if getattr(self, "_main_bounds_mm", None):
                min_x, max_x, min_y, max_y = self._main_bounds_mm
                pad_x = max(6.0, (max_x - min_x) * 0.08)
                pad_y = max(6.0, (max_y - min_y) * 0.08)
                p1 = self.mm_to_scene(min_x - pad_x, max_y + pad_y)
                p2 = self.mm_to_scene(max_x + pad_x, min_y - pad_y)
                rect = QRectF(p1, p2).normalized()
            else:
                rect = self.scene.itemsBoundingRect().adjusted(-10, -10, 10, 10)

            if rect.isValid() and not rect.isEmpty():
                self.fitInView(rect, Qt.KeepAspectRatio)
                self._user_has_zoomed = False
        finally:
            self._in_fit_view = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not getattr(self, '_user_has_zoomed', False) and getattr(self, '_has_fitted_once', False):
            self.fit_view()
        self.view_changed.emit()

    def scrollContentsBy(self, dx, dy):
        """Override de bat MOI thay doi cuon (bao gom ca do fitInView()/scale()
        gay ra ben trong Qt, khong chi thao tac keo thu cong) - noi tap trung
        duy nhat de phat view_changed, dam bao thuoc do luon dong bo voi canvas."""
        super().scrollContentsBy(dx, dy)
        self.view_changed.emit()

    def render_program(self, result: ParseResult, sheet_w: float = None, sheet_h: float = None):
        # luu lai transform (zoom/pan) hien tai truoc khi xoa scene, vi scene.clear()
        # khong lam mat transform cua view, nhung ta van can fitInView co kiem soat
        self._bg_pixmap_item = None  # da bi xoa boi scene.clear()
        self._hover_marker_items = []
        self._guide_line_item = None
        self._measure_line_item = None
        self._measure_dot_items = []
        self.scene.clear()
        self._redraw_background()
        self._segments = result.segments
        self._known_points_mm = self._collect_known_points(result.segments)

        # Khi chua co doan G-code nao (vd vua mo ung dung, editor con trong), hien thi
        # san mot he truc toa do co kich thuoc mac dinh de nguoi dung de hinh dung,
        # voi goc (0,0) nam o GOC DUOI-TRAI cua khung nhin (khong phai o giua).
        DEFAULT_VIEW_SIZE_MM = 200.0

        xs, ys = [0.0], [0.0]
        for seg in result.segments:
            xs += [seg.x0, seg.x1]
            ys += [seg.y0, seg.y1]

        if self._bg_image_path is not None:
            ax, ay = self._offset_a_mm
            sx, sy = self._px_per_mm_xy()
            img_w_mm = self._bg_image_w_px / sx
            img_h_mm = self._bg_image_h_px / sy
            xs += [ax, ax + img_w_mm]
            ys += [ay, ay + img_h_mm]

        actual_w = max(xs)
        actual_h = max(ys)
        if sheet_w:
            actual_w = max(actual_w, sheet_w)
        if sheet_h:
            actual_h = max(actual_h, sheet_h)

        if not result.segments and self._bg_image_path is None and not sheet_w and not sheet_h:
            actual_w = DEFAULT_VIEW_SIZE_MM
            actual_h = DEFAULT_VIEW_SIZE_MM

        min_work_x = min(0.0, min(xs))
        min_work_y = min(0.0, min(ys))
        self._main_bounds_mm = (min_work_x, actual_w, min_work_y, actual_h)

        min_x = min_work_x - 5
        max_x = actual_w + 5
        min_y = min_work_y - 5
        max_y = actual_h + 5

        self._last_grid_bounds = (min_x, max_x, min_y, max_y)
        self._draw_grid(min_x, max_x, min_y, max_y)
        self._draw_axes(min_x, max_x, min_y, max_y)

        for seg in result.segments:
            pen = self._pen_rapid if seg.rapid else self._pen_cut
            if seg.kind == "line":
                self.scene.addLine(*self._gcode_line_coords(seg.x0, seg.y0, seg.x1, seg.y1), pen)
            else:
                pts = arc_to_polyline(seg)
                for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                    self.scene.addLine(*self._gcode_line_coords(ax, ay, bx, by), pen)

        # danh dau diem cuoi (vi tri dao hien tai)
        p = self.real_mm_to_scene(result.end_x, result.end_y)
        r = 4
        self.scene.addEllipse(p.x() - r, p.y() - r, 2 * r, 2 * r,
                               QPen(QColor("#16a34a"), 1.5))

        rect = self.scene.itemsBoundingRect().adjusted(-10, -10, 10, 10)
        self.scene.setSceneRect(rect)

        # CHI can khung nhin tu dong o lan render DAU TIEN (vd luc vua mo file/vua go
        # chuong trinh moi). Nhung lan sau (go them dong, doi mau, doi thong so anh...)
        # GIU NGUYEN vi tri zoom/pan hien tai cua nguoi dung thay vi reset ve fit toan bo.
        if not self._has_fitted_once:
            self.fit_view()
            self._has_fitted_once = True

    @staticmethod
    def _collect_known_points(segments) -> list:
        """Gom danh sach cac diem X/Y (mm THAT, tuyet doi) DA XUAT HIEN trong
        chuong trinh G-code hien tai (diem dau + diem cuoi cua moi doan), khu
        trung lap - dung de SNAP vao khi nguoi dung ho ren/click gan 1 diem
        DA CO SAN, giup noi lien mach chinh xac tuyet doi (khac snap luoi, la
        snap theo buoc luoi co dinh chu khong phai theo diem thuc te)."""
        seen = set()
        points = []
        for seg in segments:
            for x, y in ((seg.x0, seg.y0), (seg.x1, seg.y1)):
                key = (round(x, 6), round(y, 6))
                if key not in seen:
                    seen.add(key)
                    points.append((x, y))
        return points

    def _line_coords(self, x0, y0, x1, y1):
        p0 = self.mm_to_scene(x0, y0)
        p1 = self.mm_to_scene(x1, y1)
        return p0.x(), p0.y(), p1.x(), p1.y()

    def _gcode_line_coords(self, x0, y0, x1, y1):
        """Nhu _line_coords nhung dung real_mm_to_scene() - danh rieng cho duong
        chay dao ve tu G-code, de trung khop dung pixel anh nen theo calibration."""
        p0 = self.real_mm_to_scene(x0, y0)
        p1 = self.real_mm_to_scene(x1, y1)
        return p0.x(), p0.y(), p1.x(), p1.y()

    def set_grid_step(self, step_mm: float):
        self._grid_step_mm = max(0.001, step_mm)

    _MAX_GRID_LINES = 2000  # tran an toan moi truc, tranh treo UI neu buoc luoi qua nho so voi vung ve

    def _draw_grid(self, min_x, max_x, min_y, max_y, step=None):
        import math
        if step is None:
            step = self._grid_step_mm
        if step <= 0:
            return
        # Neu buoc luoi qua nho so voi kich thuoc vung ve (vd nguoi dung nhap
        # 0.01mm cho phoi 10000mm), so duong luoi co the len toi hang trieu ->
        # treo UI thread hoan toan (moi duong la 1 QGraphicsLineItem, khong co
        # gioi han nao khac). Tang buoc thuc te len de khong vuot qua
        # _MAX_GRID_LINES duong tren moi truc, van giu ty le boi cua step goc.
        n_x = (max_x - min_x) / step
        n_y = (max_y - min_y) / step
        effective_step = step
        n_max = max(n_x, n_y)
        if n_max > self._MAX_GRID_LINES:
            multiplier = math.ceil(n_max / self._MAX_GRID_LINES)
            effective_step = step * multiplier

        gx0 = math.floor(min_x / effective_step) * effective_step
        gy0 = math.floor(min_y / effective_step) * effective_step
        x = gx0
        while x <= max_x:
            self.scene.addLine(*self._line_coords(x, min_y, x, max_y), self._pen_grid)
            x += effective_step
        y = gy0
        while y <= max_y:
            self.scene.addLine(*self._line_coords(min_x, y, max_x, y), self._pen_grid)
            y += effective_step

    def _draw_axes(self, min_x, max_x, min_y, max_y):
        self.scene.addLine(*self._line_coords(min_x, 0, max_x, 0), self._pen_axis)
        self.scene.addLine(*self._line_coords(0, min_y, 0, max_y), self._pen_axis)

    # ---------- duong ke huong dan (guide line) khi keo vach chia thuoc do ----------

    def show_guide_line(self, axis: str, mm_pos: float):
        """Ve 1 duong ke tam thoi XUYEN SUOT ban ve, tai vi tri mm_pos tren
        truc axis ('x': duong doc tai X=mm_pos, 'y': duong ngang tai Y=mm_pos)
        - dung khi nguoi dung dang KEO 1 vach chia tren thuoc do, giup can
        chinh chinh xac theo cac chi tiet trong anh nen."""
        if self._guide_line_item is not None:
            self.scene.removeItem(self._guide_line_item)
            self._guide_line_item = None
        min_x, max_x, min_y, max_y = self._last_grid_bounds
        pen = QPen(QColor(self._colors["hover"]), 1.0, Qt.DashLine)
        if axis == "x":
            line = self.scene.addLine(*self._line_coords(mm_pos, min_y, mm_pos, max_y), pen)
        else:
            line = self.scene.addLine(*self._line_coords(min_x, mm_pos, max_x, mm_pos), pen)
        line.setZValue(60)
        self._guide_line_item = line

    def clear_guide_line(self):
        if self._guide_line_item is not None:
            self.scene.removeItem(self._guide_line_item)
            self._guide_line_item = None

    # ---------- cong cu do khoang cach tam thoi (khong chen vao G-code) ----------

    def show_measure_line(self, x0_mm: float, y0_mm: float, x1_mm: float, y1_mm: float):
        """Ve 1 doan thang tam thoi giua 2 diem (mm THAT) de nguoi dung xem
        truoc khoang cach/goc - KHONG lien quan gi den G-code, chi la cong cu
        do dac tham khao tren canvas. Goi lai voi diem moi se thay the doan cu."""
        self.clear_measure_line()
        pen = QPen(QColor("#f97316"), 1.6, Qt.DashLine)
        p0 = self.real_mm_to_scene(x0_mm, y0_mm)
        p1 = self.real_mm_to_scene(x1_mm, y1_mm)
        line = self.scene.addLine(p0.x(), p0.y(), p1.x(), p1.y(), pen)
        line.setZValue(70)
        self._measure_line_item = line

        r = self._marker_radius_px * 0.7
        for pt in (p0, p1):
            dot = self.scene.addEllipse(-r, -r, 2 * r, 2 * r, QPen(QColor("#f97316"), 1.6),
                                         QBrush(QColor("#f97316")))
            dot.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            dot.setPos(pt)
            dot.setZValue(71)
            self._measure_dot_items.append(dot)

    def clear_measure_line(self):
        if self._measure_line_item is not None:
            self.scene.removeItem(self._measure_line_item)
            self._measure_line_item = None
        for item in self._measure_dot_items:
            self.scene.removeItem(item)
        self._measure_dot_items = []

    # ---------- tuong tac chuot ----------
    #
    # - Chuot trai (click don gian, khong keo): chon/chen toa do tai diem click.
    # - Chuot trai (giu va keo qua nguong _DRAG_THRESHOLD_PX): pan (di chuyen hinh ve).
    # - Chuot phai: yeu cau hoan tac thao tac chen gan nhat (undo).
    # - Cuon chuot (wheel): zoom quanh vi tri con tro.
    # - Di chuyen chuot: bao toa do hien tai (co snap luoi) de hien o status bar.

    def set_snap_enabled(self, enabled: bool):
        self._snap_enabled = enabled

    def set_snap_radius(self, radius_px: float):
        self._snap_radius_px = max(0.0, radius_px)

    def set_marker_radius(self, radius_px: float):
        self._marker_radius_px = max(1.0, radius_px)

    def _find_nearby_known_point(self, pos):
        """Tim diem G-code DA CO SAN (tu _known_points_mm) gan con tro nhat,
        trong ban kinh snap TREN MAN HINH - tra ve (x_mm, y_mm) THAT (piecewise)
        cua diem do neu tim thay, None neu khong co diem nao du gan. Uu tien
        HON snap luoi (goi truoc trong _mm_at_pos) vi noi lien 2 diem CHINH XAC
        TUYET DOI quan trong hon la hut theo buoc luoi co dinh."""
        if not self._snap_enabled or not self._known_points_mm:
            return None
        best = None
        best_dist2 = self._snap_radius_px ** 2
        for x_mm, y_mm in self._known_points_mm:
            scene_pt = self.real_mm_to_scene(x_mm, y_mm)
            screen_pt = self.mapFromScene(scene_pt)
            dx = screen_pt.x() - pos.x()
            dy = screen_pt.y() - pos.y()
            dist2 = dx * dx + dy * dy
            if dist2 <= best_dist2:
                best_dist2 = dist2
                best = (x_mm, y_mm)
        return best

    def _mm_at_pos(self, pos) -> tuple[float, float]:
        """Toa do mm tai vi tri con tro man hinh, da hut vao giao diem luoi gan nhat
        neu khoang cach tren MAN HINH (px) nam trong ban kinh snap - giup click chinh xac
        hon ma khong phu thuoc vao muc zoom hien tai. Uu tien snap vao 1 DIEM G-CODE
        DA CO SAN (chinh xac tuyet doi) truoc khi thu snap theo LUOI (buoc co dinh)."""
        known = self._find_nearby_known_point(pos)
        if known is not None:
            return known

        scene_pt = self.mapToScene(pos)

        if not self._snap_enabled or self._grid_step_mm <= 0:
            return self.scene_to_real_mm(scene_pt)

        # Luoi (grid) duoc ve theo he toa do HIEN THI co dinh (mm_to_scene/scene_to_mm),
        # nen viec snap cung phai tinh tren he do de dung vi tri giao diem luoi tren
        # man hinh; chi sau khi xac dinh duoc DIEM SCENE cuoi cung moi quy doi sang
        # mm THAT (piecewise) de tra ve.
        x_mm, y_mm = self.scene_to_mm(scene_pt)
        step = self._grid_step_mm
        gx_mm = round(x_mm / step) * step
        gy_mm = round(y_mm / step) * step

        grid_scene = self.mm_to_scene(gx_mm, gy_mm)
        grid_screen = self.mapFromScene(grid_scene)
        dx_px = grid_screen.x() - pos.x()
        dy_px = grid_screen.y() - pos.y()
        if (dx_px * dx_px + dy_px * dy_px) ** 0.5 <= self._snap_radius_px:
            return self.scene_to_real_mm(grid_scene)
        return self.scene_to_real_mm(scene_pt)

    # Nguong (pixel) de phan biet "click chon diem" voi "giu va keo de di chuyen":
    # neu chuot di chuyen qua nguong nay trong luc dang giu nut trai, coi la keo (pan),
    # neu khong (tha chuot ma chua di chuyen qua nguong) thi coi la click chon diem.
    _DRAG_THRESHOLD_PX = 4

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.undo_requested.emit()
            return
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._last_drag_pos = event.pos()
            self._is_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        x_mm, y_mm = self._mm_at_pos(event.pos())
        self.mouse_moved_mm.emit(x_mm, y_mm)

        known = self._find_nearby_known_point(event.pos())
        if known is not None:
            self._update_hover_marker_at_known_point(known)
        else:
            # Marker/crosshair phai ve theo he HIEN THI (display, tuc scene_to_mm/mm_to_scene
            # ty le co dinh) de luon nam DUNG DUOI CON TRO man hinh - khong dung x_mm/y_mm
            # (mm THAT sau hieu chinh piecewise) vi 2 he co the lech nhau, gay marker "nhay"
            # sang mot vi tri khac noi ban vua click.
            disp_x_mm, disp_y_mm = self.scene_to_mm(self.mapToScene(event.pos()))
            self._update_hover_marker(event.pos(), disp_x_mm, disp_y_mm)

        if event.buttons() & Qt.LeftButton and getattr(self, "_press_pos", None) is not None:
            if not getattr(self, "_is_dragging", False):
                delta = event.pos() - self._press_pos
                if (delta.x() ** 2 + delta.y() ** 2) ** 0.5 >= self._DRAG_THRESHOLD_PX:
                    self._is_dragging = True
                    self._user_has_zoomed = True
                    self.setCursor(Qt.ClosedHandCursor)

            if getattr(self, "_is_dragging", False):
                # Pan bang cach dich chuyen truc tiep thanh cuon, khong dung
                # ScrollHandDrag cua Qt (tranh phai gia lap lai mousePressEvent).
                d = event.pos() - self._last_drag_pos
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
                self._last_drag_pos = event.pos()

        super().mouseMoveEvent(event)

    def _update_hover_marker_at_known_point(self, known_mm: tuple):
        """Ve marker hover khi dang SNAP vao 1 DIEM G-CODE DA CO SAN (khac mau
        voi marker snap luoi thong thuong, de nguoi dung phan biet duoc dang
        noi vao 1 diem CHINH XAC TUYET DOI thay vi chi hut theo buoc luoi)."""
        for item in self._hover_marker_items:
            self.scene.removeItem(item)
        self._hover_marker_items = []

        x_mm, y_mm = known_mm
        center = self.real_mm_to_scene(x_mm, y_mm)
        known_color = QColor("#f97316")  # cam, khac voi mau hover luoi (#3b9eff)
        r = self._marker_radius_px
        marker = self.scene.addEllipse(
            -r, -r, 2 * r, 2 * r,
            QPen(known_color, 2.0),
            QBrush(known_color.lighter(160)),
        )
        marker.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        marker.setPos(center)
        marker.setZValue(50)
        self._hover_marker_items.append(marker)

    def _update_hover_marker(self, pos, x_mm: float, y_mm: float):
        """Sang duong luoi gan con tro de de dinh vi:
          - Neu con tro du gan mot GIAO DIEM luoi (ca 2 truc, tuc _mm_at_pos da snap):
            sang CA 2 duong (ngang + doc) kieu crosshair, kem vong tron highlight.
          - Neu chi gan MOT duong luoi don le (chi 1 truc, chua du gan giao diem):
            chi sang DUONG DO (ngang hoac doc), khong hien vong tron."""
        for item in self._hover_marker_items:
            self.scene.removeItem(item)
        self._hover_marker_items = []

        if not self._snap_enabled or self._grid_step_mm <= 0:
            return

        step = self._grid_step_mm
        gx_mm = round(x_mm / step) * step
        gy_mm = round(y_mm / step) * step

        # khoang cach tren MAN HINH (px) tu con tro den duong luoi doc (X=gx_mm)
        # va duong luoi ngang (Y=gy_mm) gan nhat, de so sanh voi ban kinh snap.
        vx_screen = self.mapFromScene(self.mm_to_scene(gx_mm, y_mm))
        hy_screen = self.mapFromScene(self.mm_to_scene(x_mm, gy_mm))
        dist_v = abs(vx_screen.x() - pos.x())
        dist_h = abs(hy_screen.y() - pos.y())

        near_v = dist_v <= self._snap_radius_px
        near_h = dist_h <= self._snap_radius_px
        is_snapped = near_v and near_h

        min_x, max_x, min_y, max_y = self._last_grid_bounds

        if is_snapped:
            hover_color = QColor(self._colors["hover"])

            line_h = self.scene.addLine(*self._line_coords(min_x, gy_mm, max_x, gy_mm), self._pen_hover_line)
            line_v = self.scene.addLine(*self._line_coords(gx_mm, min_y, gx_mm, max_y), self._pen_hover_line)
            line_h.setZValue(40)
            line_v.setZValue(40)
            self._hover_marker_items += [line_h, line_v]

            # Ban kinh CO DINH theo PIXEL MAN HINH (khong to/nho theo zoom): dat co
            # ItemIgnoresTransformations, ve hinh quanh goc (0,0) roi setPos() den
            # dung vi tri scene - Qt se giu nguyen kich thuoc hien thi bat ke zoom.
            center = self.mm_to_scene(gx_mm, gy_mm)
            r = self._marker_radius_px
            marker = self.scene.addEllipse(
                -r, -r, 2 * r, 2 * r,
                QPen(hover_color, 1.6),
                QBrush(hover_color.lighter(160)),
            )
            marker.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            marker.setPos(center)
            marker.setZValue(50)
            self._hover_marker_items.append(marker)
        elif near_v:
            line_v = self.scene.addLine(*self._line_coords(gx_mm, min_y, gx_mm, max_y), self._pen_hover_line)
            line_v.setZValue(40)
            self._hover_marker_items.append(line_v)
        elif near_h:
            line_h = self.scene.addLine(*self._line_coords(min_x, gy_mm, max_x, gy_mm), self._pen_hover_line)
            line_h.setZValue(40)
            self._hover_marker_items.append(line_h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_dragging = getattr(self, "_is_dragging", False)
            if was_dragging:
                self.setCursor(Qt.ArrowCursor)
            else:
                # tha chuot ma chua tung vuot qua nguong keo -> la mot cai click don
                # gian, chon toa do tai vi tri hien tai (co snap luoi neu du gan).
                x_mm, y_mm = self._mm_at_pos(event.pos())
                x_mm = round(x_mm, 6)
                y_mm = round(y_mm, 6)
                self._last_click_mm = (x_mm, y_mm)
                self.point_clicked.emit(x_mm, y_mm)
            self._press_pos = None
            self._is_dragging = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        self._user_has_zoomed = True
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self.view_changed.emit()

    @property
    def last_click_mm(self):
        return self._last_click_mm
