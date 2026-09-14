"""
Bo phan tich cu phap (parser) G-code thuan Python, khong dung AI/ML.

Ho tro cac lenh co ban thuong dung trong phay CNC 2D/2.5D:
  G90 / G91      - che do toa do tuyet doi / tuong doi
  G0  / G1       - di chuyen thang (nhanh / cat)
  G2  / G3       - noi cung theo chieu kim dong ho / nguoc chieu kim dong ho
                   (dung tam I, J tuong doi so voi diem bat dau cung)
  X, Y           - toa do dich
  I, J           - do lech tam cung so voi diem bat dau (luon la gia tri tuong doi)
  F, S, M...     - duoc bo qua (khong anh huong hinh hoc) nhung khong gay loi

Ket qua tra ve la danh sach cac "Segment" mo ta hinh hoc duong chay dao,
da duoc quy doi ve toa do TUYET DOI (mm), du dong lenh goc dung G90 hay G91.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import math
import re

_TOKEN_RE = re.compile(r"([A-Za-z])\s*(-?\d+\.?\d*)")


@dataclass
class Segment:
    kind: str          # "line" hoac "arc"
    x0: float
    y0: float
    x1: float
    y1: float
    rapid: bool = False        # True neu la G0 (di chuyen nhanh, khong cat)
    cw: Optional[bool] = None  # chi dung cho arc: True = G2, False = G3
    cx: float = 0.0            # tam cung (chi dung cho arc)
    cy: float = 0.0
    source_line: int = -1      # so dong trong van ban goc, de highlight


@dataclass
class ParseResult:
    segments: List[Segment]
    # vi tri con dao sau khi thuc hien toan bo chuong trinh
    end_x: float
    end_y: float
    # canh bao / loi phat hien duoc (khong lam dung chuong trinh)
    warnings: List[str]


def _strip_comment(line: str) -> str:
    # bo comment dang ; ... hoac ( ... )
    line = line.split(";", 1)[0]
    line = re.sub(r"\([^)]*\)", "", line)
    return line.strip()


def parse_gcode(text: str, start_x: float = 0.0, start_y: float = 0.0) -> ParseResult:
    segments: List[Segment] = []
    warnings: List[str] = []

    absolute_mode = True  # G90 la mac dinh theo chuan
    cur_x, cur_y = start_x, start_y

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line)
        if not line:
            continue

        tokens = _TOKEN_RE.findall(line.upper())
        if not tokens:
            continue

        words = {}
        g_codes = []
        for letter, value in tokens:
            if letter == "G":
                g_codes.append(int(float(value)))
            else:
                words[letter] = float(value)

        for g in g_codes:
            if g == 90:
                absolute_mode = True
            elif g == 91:
                absolute_mode = False

        motion_g = next((g for g in g_codes if g in (0, 1, 2, 3)), None)
        if motion_g is None and ("X" not in words and "Y" not in words):
            continue  # dong nay khong chua chuyen dong (vd chi co M, S, F rieng)

        target_x = cur_x
        target_y = cur_y
        if "X" in words:
            target_x = words["X"] if absolute_mode else cur_x + words["X"]
        if "Y" in words:
            target_y = words["Y"] if absolute_mode else cur_y + words["Y"]

        if motion_g in (0, 1) or motion_g is None:
            segments.append(Segment(
                kind="line", x0=cur_x, y0=cur_y, x1=target_x, y1=target_y,
                rapid=(motion_g == 0), source_line=lineno,
            ))
        elif motion_g in (2, 3):
            i = words.get("I", 0.0)
            j = words.get("J", 0.0)
            cx = cur_x + i
            cy = cur_y + j
            segments.append(Segment(
                kind="arc", x0=cur_x, y0=cur_y, x1=target_x, y1=target_y,
                cw=(motion_g == 2), cx=cx, cy=cy, source_line=lineno,
            ))

        cur_x, cur_y = target_x, target_y

    return ParseResult(segments=segments, end_x=cur_x, end_y=cur_y, warnings=warnings)


def arc_to_polyline(seg: Segment, max_segments: int = 64) -> List[Tuple[float, float]]:
    """Chuyen mot cung tron (arc) thanh danh sach diem de ve (khong dung thu vien do hoa nao)."""
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
    n = max(2, int(max_segments * sweep / (2 * math.pi)) + 1)

    points = []
    for k in range(n + 1):
        t = a0 + (a1 - a0) * k / n
        points.append((seg.cx + r0 * math.cos(t), seg.cy + r0 * math.sin(t)))
    return points
