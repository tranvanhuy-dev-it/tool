"""
Vung ve (canvas) hien thi duong chay dao CNC.

Khong dung AI/ML: toan bo la hinh hoc thuan tuy (QPainter ve line/arc da duoc
roi rac hoa thanh polyline boi gcode_parser.arc_to_polyline).

He quy chieu: goc (0,0) o GOC DUOI TRAI cua vung ve, truc X sang phai,
truc Y huong LEN (giong ban ve co khi / CNC thuc te), khac voi he toa do
man hinh mac dinh cua Qt (goc tren trai, Y huong xuong) -> can quy doi.
"""

from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsPixmapItem
from PyQt5.QtGui import QPen, QColor, QPainter, QFont, QPixmap
from PyQt5.QtCore import Qt, QPointF, pyqtSignal

from gcode_parser import ParseResult, Segment, arc_to_polyline

MM_TO_PX = 4.0          # ty le hien thi: 1 mm ban ve = 4 px man hinh
MARGIN_PX = 40           # le trang de con hien thi truc va nhan toa do


class CanvasWidget(QGraphicsView):
    # phat tin hieu khi nguoi dung click vao ban ve: toa do (mm) trong he tuyet doi
    point_clicked = pyqtSignal(float, float)
    # phat tin hieu khi nguoi dung click CHUOT PHAI: yeu cau hoan tac thao tac gan nhat
    undo_requested = pyqtSignal()
    # phat tin hieu lien tuc khi di chuyen chuot tren canvas: toa do (mm), da snap luoi neu du gan
    mouse_moved_mm = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor("#ffffff"))

        self._last_click_mm = None   # diem click gan nhat, dung cho toa do tuong doi
        self._origin_px = QPointF(MARGIN_PX, 0)  # cap nhat khi resize/draw
        self._segments: list[Segment] = []

        self._pen_cut = QPen(QColor("#1e293b"), 1.4)
        self._pen_rapid = QPen(QColor("#94a3b8"), 1.0, Qt.DashLine)
        self._pen_axis = QPen(QColor("#ef4444"), 1.2)
        self._pen_grid = QPen(QColor("#e5e7eb"), 0.6)

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
        self._bg_opacity = 0.5
        self._grid_step_mm = 5.0
        self._snap_enabled = True
        self._snap_radius_px = 10.0  # ban kinh hut luoi, tinh theo PIXEL MAN HINH (khong doi theo zoom)

    # ---------- anh nen ----------

    def set_background_image(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            raise ValueError(f"Khong the nap anh: {path}")
        self._bg_image_path = path
        self._bg_source_pixmap = pix
        self._bg_image_w_px = float(pix.width())
        self._bg_image_h_px = float(pix.height())
        self._redraw_background()

    def set_background_opacity(self, value: float):
        self._bg_opacity = max(0.0, min(1.0, value))
        if self._bg_pixmap_item:
            self._bg_pixmap_item.setOpacity(self._bg_opacity)

    def set_workpiece_size(self, width_mm: float, height_mm: float):
        """Kich thuoc THUC TE (mm) cua phoi, tuong ung voi toan bo chieu rong/cao
        cua anh da crop. Dung de tinh ty le px/mm rieng cho truc X va truc Y."""
        self._workpiece_w_mm = max(1e-6, width_mm)
        self._workpiece_h_mm = max(1e-6, height_mm)
        self._redraw_background()

    def set_offset_a(self, a_x_mm: float, a_y_mm: float):
        """Tham so 'a': do lech (mm) tu goc DUOI-TRAI cua anh den goc toa do
        gia cong that (0,0) ma may CNC se dung. Nguoi dung chinh tuy y."""
        self._offset_a_mm = (a_x_mm, a_y_mm)
        self._redraw_background()

    def _px_per_mm_xy(self) -> tuple[float, float]:
        return (self._bg_image_w_px / self._workpiece_w_mm,
                self._bg_image_h_px / self._workpiece_h_mm)

    def image_px_to_mm(self, ix: float, iy: float) -> tuple[float, float]:
        """Quy doi toa do pixel trong ANH GOC (0,0 tren-trai, Y huong xuong) sang
        toa do gia cong that (mm), da cong offset a."""
        sx, sy = self._px_per_mm_xy()
        ax, ay = self._offset_a_mm
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

    # ---------- ve lai toan bo ----------

    def render_program(self, result: ParseResult, sheet_w: float = None, sheet_h: float = None):
        self.scene.clear()
        self._bg_pixmap_item = None  # da bi xoa boi scene.clear()
        self._redraw_background()
        self._segments = result.segments

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

        min_x, max_x = min(xs) - 10, max(xs) + 10
        min_y, max_y = min(ys) - 10, max(ys) + 10
        if sheet_w:
            max_x = max(max_x, sheet_w + 10)
        if sheet_h:
            max_y = max(max_y, sheet_h + 10)

        self._draw_grid(min_x, max_x, min_y, max_y)
        self._draw_axes(min_x, max_x, min_y, max_y)

        for seg in result.segments:
            pen = self._pen_rapid if seg.rapid else self._pen_cut
            if seg.kind == "line":
                self.scene.addLine(
                    *self._line_coords(seg.x0, seg.y0, seg.x1, seg.y1), pen)
            else:
                pts = arc_to_polyline(seg)
                for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                    self.scene.addLine(*self._line_coords(ax, ay, bx, by), pen)

        # danh dau diem cuoi (vi tri dao hien tai)
        p = self.mm_to_scene(result.end_x, result.end_y)
        r = 4
        self.scene.addEllipse(p.x() - r, p.y() - r, 2 * r, 2 * r,
                               QPen(QColor("#16a34a"), 1.5))

        rect = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        self.scene.setSceneRect(rect)
        self.fitInView(rect, Qt.KeepAspectRatio)

    def _line_coords(self, x0, y0, x1, y1):
        p0 = self.mm_to_scene(x0, y0)
        p1 = self.mm_to_scene(x1, y1)
        return p0.x(), p0.y(), p1.x(), p1.y()

    def set_grid_step(self, step_mm: float):
        self._grid_step_mm = max(0.001, step_mm)

    def _draw_grid(self, min_x, max_x, min_y, max_y, step=None):
        import math
        if step is None:
            step = self._grid_step_mm
        gx0 = math.floor(min_x / step) * step
        gy0 = math.floor(min_y / step) * step
        x = gx0
        while x <= max_x:
            self.scene.addLine(*self._line_coords(x, min_y, x, max_y), self._pen_grid)
            x += step
        y = gy0
        while y <= max_y:
            self.scene.addLine(*self._line_coords(min_x, y, max_x, y), self._pen_grid)
            y += step

    def _draw_axes(self, min_x, max_x, min_y, max_y):
        self.scene.addLine(*self._line_coords(min_x, 0, max_x, 0), self._pen_axis)
        self.scene.addLine(*self._line_coords(0, min_y, 0, max_y), self._pen_axis)

    # ---------- tuong tac chuot ----------
    #
    # - Chuot trai: chen toa do tai diem click (hanh vi chinh).
    # - Chuot phai: yeu cau hoan tac thao tac chen gan nhat (undo).
    # - Ctrl + keo chuot trai: pan (di chuyen) hinh ve thay vi chen toa do.
    # - Cuon chuot (wheel): zoom, khong doi.
    # - Di chuyen chuot: bao toa do hien tai (co snap luoi) de hien o status bar.

    def set_snap_enabled(self, enabled: bool):
        self._snap_enabled = enabled

    def set_snap_radius(self, radius_px: float):
        self._snap_radius_px = max(0.0, radius_px)

    def _mm_at_pos(self, pos) -> tuple[float, float]:
        """Toa do mm tai vi tri con tro man hinh, da hut vao giao diem luoi gan nhat
        neu khoang cach tren MAN HINH (px) nam trong ban kinh snap - giup click chinh xac
        hon ma khong phu thuoc vao muc zoom hien tai."""
        scene_pt = self.mapToScene(pos)
        x_mm, y_mm = self.scene_to_mm(scene_pt)

        if not self._snap_enabled or self._grid_step_mm <= 0:
            return x_mm, y_mm

        step = self._grid_step_mm
        gx_mm = round(x_mm / step) * step
        gy_mm = round(y_mm / step) * step

        grid_scene = self.mm_to_scene(gx_mm, gy_mm)
        grid_screen = self.mapFromScene(grid_scene)
        dx_px = grid_screen.x() - pos.x()
        dy_px = grid_screen.y() - pos.y()
        if (dx_px * dx_px + dy_px * dy_px) ** 0.5 <= self._snap_radius_px:
            return gx_mm, gy_mm
        return x_mm, y_mm

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.undo_requested.emit()
            return
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                self.setDragMode(QGraphicsView.ScrollHandDrag)
                super().mousePressEvent(event)
                return
            x_mm, y_mm = self._mm_at_pos(event.pos())
            x_mm = round(x_mm, 6)
            y_mm = round(y_mm, 6)
            self._last_click_mm = (x_mm, y_mm)
            self.point_clicked.emit(x_mm, y_mm)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        x_mm, y_mm = self._mm_at_pos(event.pos())
        self.mouse_moved_mm.emit(x_mm, y_mm)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.dragMode() == QGraphicsView.ScrollHandDrag:
            self.setDragMode(QGraphicsView.NoDrag)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    @property
    def last_click_mm(self):
        return self._last_click_mm
