"""
Bo trich xuat duong net hinh hoc (vector hoa) tu anh ban ve ky thuat.

KHONG dung AI / machine learning. Toan bo dua tren xu ly anh co dien
(classical computer vision) cua OpenCV:
  1. Chuyen anh sang grayscale + lam sac net bien (Canny edge detection).
  2. Phat hien duong thang bang phep bien doi Hough (HoughLinesP).
  3. Phat hien duong tron / lo bang phep bien doi Hough cho hinh tron
     (HoughCircles).
  4. Gop cac doan thang gan nhau/thang hang thanh mot polyline de giam nhieu.

Ket qua tra ve la danh sach cac primitive hinh hoc theo toa do PIXEL cua
anh goc (chua quy doi sang mm) - viec quy doi ty le pixel->mm va chinh sua
duoc thuc hien thu cong boi nguoi dung trong giao dien (hieu chuan bang
2 diem tham chieu).
"""

from dataclasses import dataclass
from typing import List, Tuple
import numpy as np
import cv2


@dataclass
class DetectedLine:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class DetectedCircle:
    cx: float
    cy: float
    r: float


@dataclass
class VectorizeResult:
    lines: List[DetectedLine]
    circles: List[DetectedCircle]
    image_width: int
    image_height: int


def vectorize_image(
    image_path: str,
    canny_low: int = 50,
    canny_high: int = 150,
    hough_threshold: int = 60,
    min_line_length: int = 25,
    max_line_gap: int = 8,
    circle_min_radius: int = 6,
    circle_max_radius: int = 80,
) -> VectorizeResult:
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Khong doc duoc anh: {image_path}")

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # --- phat hien duong thang ---
    edges = cv2.Canny(blurred, canny_low, canny_high)
    raw_lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=hough_threshold,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )
    lines: List[DetectedLine] = []
    if raw_lines is not None:
        for l in raw_lines:
            x0, y0, x1, y1 = l.reshape(-1)
            lines.append(DetectedLine(float(x0), float(y0), float(x1), float(y1)))
    lines = _merge_collinear_lines(lines)

    # --- phat hien duong tron (lo khoan) ---
    circles: List[DetectedCircle] = []
    raw_circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=20,
        param1=canny_high, param2=30,
        minRadius=circle_min_radius, maxRadius=circle_max_radius,
    )
    if raw_circles is not None:
        for c in raw_circles[0]:
            cx, cy, r = c
            circles.append(DetectedCircle(float(cx), float(cy), float(r)))

    return VectorizeResult(lines=lines, circles=circles, image_width=w, image_height=h)


def _line_angle(l: DetectedLine) -> float:
    return np.arctan2(l.y1 - l.y0, l.x1 - l.x0) % np.pi


def _merge_collinear_lines(lines: List[DetectedLine], angle_tol: float = 0.03,
                            dist_tol: float = 6.0) -> List[DetectedLine]:
    """Gop cac doan thang ngan, cung phuong va gan nhau (do Hough hay bi vun)
    thanh mot doan dai hon, giam nhieu truoc khi hien thi cho nguoi dung."""
    if not lines:
        return []

    used = [False] * len(lines)
    merged: List[DetectedLine] = []

    for i, li in enumerate(lines):
        if used[i]:
            continue
        group = [li]
        used[i] = True
        angle_i = _line_angle(li)

        changed = True
        while changed:
            changed = False
            for j, lj in enumerate(lines):
                if used[j]:
                    continue
                if abs(_line_angle(lj) - angle_i) > angle_tol:
                    continue
                # kiem tra khoang cach tu diem cua lj den duong thang cua nhom
                if _point_near_segment(lj.x0, lj.y0, group, dist_tol) or \
                   _point_near_segment(lj.x1, lj.y1, group, dist_tol):
                    group.append(lj)
                    used[j] = True
                    changed = True

        xs = [p for seg in group for p in (seg.x0, seg.x1)]
        ys = [p for seg in group for p in (seg.y0, seg.y1)]
        # lay 2 diem xa nhau nhat trong nhom lam doan gop
        pts = list(zip(xs, ys))
        best_pair = max(
            ((a, b) for idx, a in enumerate(pts) for b in pts[idx + 1:]),
            key=lambda ab: (ab[0][0] - ab[1][0]) ** 2 + (ab[0][1] - ab[1][1]) ** 2,
            default=((xs[0], ys[0]), (xs[0], ys[0])),
        )
        (ax, ay), (bx, by) = best_pair
        merged.append(DetectedLine(ax, ay, bx, by))

    return merged


def _point_near_segment(px, py, group, tol) -> bool:
    for seg in group:
        for (gx, gy) in ((seg.x0, seg.y0), (seg.x1, seg.y1)):
            if (px - gx) ** 2 + (py - gy) ** 2 <= tol ** 2:
                return True
    return False
