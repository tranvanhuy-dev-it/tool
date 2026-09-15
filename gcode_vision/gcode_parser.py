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
    feed_rate: float = 0.0     # F hien hanh (mm/phut) tai doan nay, 0 neu chua tung khai bao F


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
    cur_feed = 0.0  # F "modal": giu nguyen gia tri tu dong truoc cho toi khi co F moi
    cur_motion_g = None  # lenh chuyen dong (G0/G1/G2/G3) "modal": ke thua tu dong truoc neu dong nay khong ghi G nao
    warned_missing_feed = False

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

        if "F" in words:
            cur_feed = words["F"]

        motion_g_explicit = next((g for g in g_codes if g in (0, 1, 2, 3)), None)
        if motion_g_explicit is None and ("X" not in words and "Y" not in words):
            continue  # dong nay khong chua chuyen dong (vd chi co M, S, F rieng)

        # G0/G1/G2/G3 la lenh "modal" theo dung chuan G-code: neu dong nay
        # KHONG ghi G nao ca nhung co X/Y, no KE THUA dung lenh G cua dong
        # CHUYEN DONG gan nhat (vd nhieu dong lien tiep chi ghi "X.. Y.."
        # sau 1 lan G1 duy nhat) - PHAI dung gia tri modal nay (khong phai
        # gia dinh la G1) de xac dinh dung la rapid (G0, khong can F, ve net
        # dut) hay la cat (G1/G2/G3, can F, ve net lien), tranh canh bao F
        # nham cho cac dong dang ke thua G0.
        if motion_g_explicit is not None:
            cur_motion_g = motion_g_explicit
        motion_g = cur_motion_g if cur_motion_g is not None else 1  # chua tung co G nao truoc do -> gia dinh G1 (mac dinh chuan)

        target_x = cur_x
        target_y = cur_y
        if "X" in words:
            target_x = words["X"] if absolute_mode else cur_x + words["X"]
        if "Y" in words:
            target_y = words["Y"] if absolute_mode else cur_y + words["Y"]

        is_cutting_move = motion_g in (1, 2, 3)
        if is_cutting_move and cur_feed <= 0 and not warned_missing_feed:
            g_label = f"G{motion_g}" if motion_g_explicit is not None else f"G{motion_g} (kế thừa, không ghi lại)"
            warnings.append(
                f"Dòng {lineno}: lệnh cắt ({g_label}) chưa có tốc độ F nào được "
                f"khai báo trước đó — máy CNC có thể chạy với tốc độ mặc định "
                f"không mong muốn."
            )
            warned_missing_feed = True

        if motion_g in (0, 1):
            segments.append(Segment(
                kind="line", x0=cur_x, y0=cur_y, x1=target_x, y1=target_y,
                rapid=(motion_g == 0), source_line=lineno, feed_rate=cur_feed,
            ))
        elif motion_g in (2, 3):
            # Khac voi G/F, cac tham so I/J KHONG modal theo chuan G-code:
            # moi lenh G2/G3 rieng le PHAI tu khai bao I/J cua chinh no (tam
            # cung tinh TUONG DOI so voi diem BAT DAU cua dung cung do, khac
            # nhau moi lan). Neu dong nay dang KE THUA G2/G3 modal (khong tu
            # ghi lai G) ma cung KHONG ghi I hoac J, mac dinh I/J=0 se lam tam
            # cung trung diem bat dau -> cung ban kinh 0, vo nghia/sai hoan
            # toan - phai canh bao ro cho nguoi dung, khac voi truong hop
            # thieu F (chi la canh bao ve toc do, khong lam sai hinh hoc).
            if "I" not in words and "J" not in words:
                warnings.append(
                    f"Dòng {lineno}: lệnh cung tròn (G{motion_g}) không ghi tham số "
                    f"I/J (tâm cung) — I/J không kế thừa từ dòng trước theo chuẩn "
                    f"G-code, cung tròn này có thể bị tính sai (bán kính 0)."
                )
            i = words.get("I", 0.0)
            j = words.get("J", 0.0)
            cx = cur_x + i
            cy = cur_y + j
            segments.append(Segment(
                kind="arc", x0=cur_x, y0=cur_y, x1=target_x, y1=target_y,
                cw=(motion_g == 2), cx=cx, cy=cy, source_line=lineno, feed_rate=cur_feed,
            ))

        cur_x, cur_y = target_x, target_y

    return ParseResult(segments=segments, end_x=cur_x, end_y=cur_y, warnings=warnings)


_DEFAULT_RAPID_MM_PER_MIN = 5000.0   # toc do G0 gia dinh khi uoc tinh thoi gian (khong the biet chinh xac tu G-code chuan)
_DEFAULT_CUT_MM_PER_MIN = 500.0      # toc do CAT gia dinh khi doan chua tung khai bao F nao (tranh chia cho ~0 -> thoi gian "vo cuc")


def estimate_machining_time_seconds(segments: List[Segment],
                                     rapid_mm_per_min: float = _DEFAULT_RAPID_MM_PER_MIN) -> float:
    """Uoc tinh THOI GIAN gia cong (giay) bang cach cong don thoi gian di
    chuyen cua tung doan: doan CAT (G1/G2/G3) dung dung feed_rate (F, mm/phut)
    da khai bao trong G-code, HOAC toc do gia dinh _DEFAULT_CUT_MM_PER_MIN neu
    doan do CHUA TUNG co F nao (feed_rate == 0) - tranh chia cho gia tri gan
    0 (1e-6) lam thoi gian uoc tinh bi phong dai len hang trieu lan; doan
    CHAY NHANH (G0) dung 1 toc do GIA DINH co dinh (rapid_mm_per_min) vi
    G-code chuan KHONG ghi toc do thuc cua G0 (do la thong so rieng cua tung
    may). Day la UOC LUONG THAM KHAO, khong phai thoi gian chinh xac tuyet
    doi cua may that - dac biet khi thieu F thi chi la phong doan."""
    total_seconds = 0.0
    for seg in segments:
        if seg.kind == "line":
            length_mm = math.hypot(seg.x1 - seg.x0, seg.y1 - seg.y0)
        else:
            pts = arc_to_polyline(seg)
            length_mm = sum(
                math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(pts, pts[1:])
            )
        if seg.rapid:
            feed = rapid_mm_per_min
        else:
            feed = seg.feed_rate if seg.feed_rate > 0 else _DEFAULT_CUT_MM_PER_MIN
        total_seconds += (length_mm / feed) * 60.0
    return total_seconds


def convert_gcode_mode(text: str, to_absolute: bool, decimals: int = 3,
                        start_x: float = 0.0, start_y: float = 0.0) -> str:
    """Viet lai toan bo chuong trinh G-code de chuyen doi giua he TUYET DOI
    (G90) va TUONG DOI (G91), giu nguyen hinh hoc duong chay dao (chi doi
    CACH GHI toa do, khong doi vi tri thuc te cua dao).

    Cach lam: duyet tung dong nhu parse_gcode() (theo doi tri tuyet doi hien
    tai cur_x/cur_y), nhung thay vi tao Segment, VIET LAI dung cac token X/Y
    tren dong do bang gia tri phu hop voi che do dich (to_absolute):
      - Sang TUYET DOI: ghi lai toa do TUYET DOI thuc te (target_x/target_y).
      - Sang TUONG DOI: ghi lai DO LECH so voi vi tri TRUOC do dong nay
        (target - cur), dung cong thuc tuong doi that su, khong phai suy
        dien tu G-code goc (nen luon chinh xac du file goc dang o mode nao).
    Dong G90/G91 rieng le (khong co X/Y) duoc BO QUA hoan toan (khong ghi
    lai) - dong G90/G91 DUY NHAT can co se duoc main_window chen o dau file."""
    out_lines: List[str] = []
    absolute_mode = True
    cur_x, cur_y = start_x, start_y

    for raw_line in text.splitlines():
        line = _strip_comment(raw_line)
        if not line:
            out_lines.append(raw_line)
            continue

        tokens = _TOKEN_RE.findall(line.upper())
        if not tokens:
            out_lines.append(raw_line)
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

        has_xy = "X" in words or "Y" in words
        is_pure_mode_line = (g_codes and all(g in (90, 91) for g in g_codes) and not has_xy)
        if is_pure_mode_line:
            continue  # dong CHI co G90/G91 - se duoc main_window chen lai 1 lan o dau file

        if not has_xy:
            out_lines.append(raw_line)  # dong khac (M, S, F rieng...) giu nguyen
            continue

        target_x = cur_x
        target_y = cur_y
        if "X" in words:
            target_x = words["X"] if absolute_mode else cur_x + words["X"]
        if "Y" in words:
            target_y = words["Y"] if absolute_mode else cur_y + words["Y"]

        # viet lai DUNG cac token X/Y tren dong (giu nguyen G0/G1/G2/G3, I/J,
        # F/S/M... va thu tu token khac nhu ban goc), voi gia tri MOI theo
        # dung che do dich to_absolute.
        def _replace_xy(m: re.Match) -> str:
            letter = m.group(1).upper()
            if letter == "X":
                new_val = target_x if to_absolute else (target_x - cur_x)
                return f"X{new_val:.{decimals}f}"
            if letter == "Y":
                new_val = target_y if to_absolute else (target_y - cur_y)
                return f"Y{new_val:.{decimals}f}"
            return m.group(0)

        new_line = _TOKEN_RE.sub(_replace_xy, line)
        out_lines.append(new_line)

        cur_x, cur_y = target_x, target_y

    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")


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
