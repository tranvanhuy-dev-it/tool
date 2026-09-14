"""
Module tao bieu tuong vector CAD/CAM sac net cho CNC G-code Designer.
Ve truc tiep bang QPainter tren QPixmap -> tao QIcon sac net tai moi do phan giai,
khong phu thuoc tep anh ngoai hay font emoji he dieu hanh.
"""

from PyQt5.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QBrush, QPainterPath, QPolygonF
from PyQt5.QtCore import Qt, QPointF, QRectF


def create_cad_icon(name: str, color_hex: str = "#38bdf8", size: int = 24) -> QIcon:
    """Tao QIcon vector ky thuat sac net theo ten bieu tuong, mau sac va kich thuoc (px)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    color = QColor(color_hex)
    pen = QPen(color, max(1.2, size * 0.07))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    s = float(size)
    p = s * 0.12  # padding

    if name == "new":
        # To giay ky thuat co nep gap goc tren-phai va dau cong nho
        w = s * 0.58
        h = s * 0.74
        x0 = (s - w) / 2
        y0 = (s - h) / 2
        fold = s * 0.18
        path = QPainterPath()
        path.moveTo(x0, y0)
        path.lineTo(x0 + w - fold, y0)
        path.lineTo(x0 + w, y0 + fold)
        path.lineTo(x0 + w, y0 + h)
        path.lineTo(x0, y0 + h)
        path.closeSubpath()
        painter.drawPath(path)
        # Nep gap
        painter.drawLine(QPointF(x0 + w - fold, y0), QPointF(x0 + w - fold, y0 + fold))
        painter.drawLine(QPointF(x0 + w - fold, y0 + fold), QPointF(x0 + w, y0 + fold))
        # Dau cong o giua
        cx, cy = x0 + w / 2, y0 + h / 2 + s * 0.04
        r = s * 0.12
        painter.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        painter.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))

    elif name == "open":
        # Thu muc ban ve ky thuat mo
        path = QPainterPath()
        # Nap sau
        path.moveTo(s * 0.15, s * 0.35)
        path.lineTo(s * 0.15, s * 0.28)
        path.lineTo(s * 0.42, s * 0.28)
        path.lineTo(s * 0.52, s * 0.35)
        path.lineTo(s * 0.85, s * 0.35)
        path.lineTo(s * 0.85, s * 0.75)
        path.lineTo(s * 0.15, s * 0.75)
        painter.drawPath(path)
        # Than truoc cua thu muc
        front = QPainterPath()
        front.moveTo(s * 0.12, s * 0.75)
        front.lineTo(s * 0.26, s * 0.45)
        front.lineTo(s * 0.90, s * 0.45)
        front.lineTo(s * 0.76, s * 0.75)
        front.closeSubpath()
        painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 45)))
        painter.drawPath(front)

    elif name == "save":
        # Dia mem luu tru ky thuat (floppy disk)
        rect = QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64)
        corner = s * 0.10
        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - corner, rect.top())
        path.lineTo(rect.right(), rect.top() + corner)
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        painter.drawPath(path)
        # Nhan tren dia
        painter.drawRect(QRectF(s * 0.30, s * 0.18, s * 0.40, s * 0.22))
        # Khe doc dia
        painter.drawRect(QRectF(s * 0.32, s * 0.54, s * 0.36, s * 0.28))

    elif name == "sample":
        # Ban ve mau: to giay voi cac duong net G-code
        rect = QRectF(s * 0.20, s * 0.15, s * 0.60, s * 0.70)
        painter.drawRect(rect)
        # Cac dong code
        for y_factor in (0.32, 0.46, 0.60, 0.74):
            painter.drawLine(QPointF(s * 0.30, s * y_factor), QPointF(s * 0.70, s * y_factor))

    elif name == "copy":
        # Hai to ban ve xep de len nhau
        painter.drawRect(QRectF(s * 0.30, s * 0.15, s * 0.52, s * 0.58))
        painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 40)))
        painter.drawRect(QRectF(s * 0.18, s * 0.27, s * 0.52, s * 0.58))

    elif name == "undo":
        # Mui ten uon cong quay lai
        path = QPainterPath()
        path.moveTo(s * 0.75, s * 0.72)
        path.cubicTo(s * 0.75, s * 0.36, s * 0.40, s * 0.36, s * 0.30, s * 0.48)
        painter.drawPath(path)
        # Dau mui ten
        arrow = QPainterPath()
        arrow.moveTo(s * 0.18, s * 0.48)
        arrow.lineTo(s * 0.34, s * 0.34)
        arrow.lineTo(s * 0.34, s * 0.62)
        arrow.closeSubpath()
        painter.setBrush(QBrush(color))
        painter.drawPath(arrow)

    elif name == "g90":
        # Truc toa do goc tuyet doi (X, Y) voi tam (0,0)
        painter.drawLine(QPointF(s * 0.22, s * 0.78), QPointF(s * 0.85, s * 0.78))  # truc X
        painter.drawLine(QPointF(s * 0.22, s * 0.78), QPointF(s * 0.22, s * 0.15))  # truc Y
        # Mui ten X
        painter.drawLine(QPointF(s * 0.85, s * 0.78), QPointF(s * 0.75, s * 0.70))
        painter.drawLine(QPointF(s * 0.85, s * 0.78), QPointF(s * 0.75, s * 0.86))
        # Mui ten Y
        painter.drawLine(QPointF(s * 0.22, s * 0.15), QPointF(s * 0.14, s * 0.25))
        painter.drawLine(QPointF(s * 0.22, s * 0.15), QPointF(s * 0.30, s * 0.25))
        # Vong tron goc (0,0)
        painter.drawEllipse(QPointF(s * 0.22, s * 0.78), s * 0.08, s * 0.08)

    elif name == "g91":
        # Ky hieu Delta gia so tuong doi
        path = QPainterPath()
        path.moveTo(s * 0.50, s * 0.18)
        path.lineTo(s * 0.82, s * 0.78)
        path.lineTo(s * 0.18, s * 0.78)
        path.closeSubpath()
        painter.drawPath(path)
        # Cham trung tam
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(s * 0.50, s * 0.56), s * 0.06, s * 0.06)

    elif name == "snap":
        # Tam ngam bat diem luoi
        cx, cy = s * 0.5, s * 0.5
        r = s * 0.28
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.drawLine(QPointF(cx - s * 0.40, cy), QPointF(cx + s * 0.40, cy))
        painter.drawLine(QPointF(cx, cy - s * 0.40), QPointF(cx, cy + s * 0.40))

    elif name == "image":
        # Khung ban ve / anh tham chieu
        rect = QRectF(s * 0.16, s * 0.20, s * 0.68, s * 0.60)
        painter.drawRect(rect)
        # Hinh nui / tam giac ben trong
        path = QPainterPath()
        path.moveTo(s * 0.24, s * 0.70)
        path.lineTo(s * 0.46, s * 0.44)
        path.lineTo(s * 0.58, s * 0.56)
        path.lineTo(s * 0.72, s * 0.38)
        path.lineTo(s * 0.78, s * 0.70)
        painter.drawPath(path)
        # Mat troi / goc tham chieu
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(s * 0.35, s * 0.34), s * 0.07, s * 0.07)

    elif name == "fit":
        # 4 mui ten mo rong ve 4 goc (Fit to Window)
        gap = s * 0.18
        len_a = s * 0.24
        # Tren-Trai
        painter.drawLine(QPointF(gap, gap), QPointF(gap + len_a, gap))
        painter.drawLine(QPointF(gap, gap), QPointF(gap, gap + len_a))
        # Tren-Phai
        painter.drawLine(QPointF(s - gap, gap), QPointF(s - gap - len_a, gap))
        painter.drawLine(QPointF(s - gap, gap), QPointF(s - gap, gap + len_a))
        # Duoi-Trai
        painter.drawLine(QPointF(gap, s - gap), QPointF(gap + len_a, s - gap))
        painter.drawLine(QPointF(gap, s - gap), QPointF(gap, s - gap - len_a))
        # Duoi-Phai
        painter.drawLine(QPointF(s - gap, s - gap), QPointF(s - gap - len_a, s - gap))
        painter.drawLine(QPointF(s - gap, s - gap), QPointF(s - gap, s - gap - len_a))

    elif name == "zoom_in":
        # Kinh lup dau cong
        cx, cy, r = s * 0.42, s * 0.42, s * 0.25
        painter.drawEllipse(QPointF(cx, cy), r, r)
        # Canh kinh lup
        painter.drawLine(QPointF(cx + r * 0.7, cy + r * 0.7), QPointF(s * 0.82, s * 0.82))
        # Dau cong
        painter.drawLine(QPointF(cx - s * 0.12, cy), QPointF(cx + s * 0.12, cy))
        painter.drawLine(QPointF(cx, cy - s * 0.12), QPointF(cx, cy + s * 0.12))

    elif name == "zoom_out":
        # Kinh lup dau tru
        cx, cy, r = s * 0.42, s * 0.42, s * 0.25
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.drawLine(QPointF(cx + r * 0.7, cy + r * 0.7), QPointF(s * 0.82, s * 0.82))
        # Dau tru
        painter.drawLine(QPointF(cx - s * 0.12, cy), QPointF(cx + s * 0.12, cy))

    elif name == "theme":
        # Bieu tuong nua mat trang / nua mat troi ky thuat
        cx, cy, r = s * 0.5, s * 0.5, s * 0.32
        painter.drawEllipse(QPointF(cx, cy), r, r)
        path = QPainterPath()
        path.moveTo(cx, cy - r)
        path.arcTo(QRectF(cx - r, cy - r, 2 * r, 2 * r), 90, 180)
        path.closeSubpath()
        painter.setBrush(QBrush(color))
        painter.drawPath(path)

    else:
        # Mac dinh: hinh hop ky thuat
        painter.drawRect(QRectF(p, p, s - 2 * p, s - 2 * p))

    painter.end()
    return QIcon(pixmap)

