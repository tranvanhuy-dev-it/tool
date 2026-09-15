"""
Hieu chuan ty le px/mm THEO TUNG DOAN (piecewise linear) cho 1 truc (X hoac Y).

Van de giai quyet: mot ban ve/anh chup co the co cac vung kich thuoc khong dung
ty le deu nhau (vd do nguoi ve ghi sai so, hoac anh bi bien dang cuc bo) - neu
chi dung 1 ty le px/mm duy nhat cho ca truc, cac diem cang xa goc se cang bi
lech so voi kich thuoc that duoc ghi tren ban ve.

Giai phap: chia truc thanh nhieu DOAN (segment), moi doan co ty le px/mm RIENG,
dua tren khoang cach pixel thuc te va do dai mm nguoi dung tu do/nhap cho doan
do. Quy doi 1 diem pixel bat ky sang mm bang noi suy tuyen tinh trong dung doan
chua no (hoac ngoai suy neu nam ngoai pham vi da hieu chuan).

Khong dung AI/ML: thuan tuy noi suy tuyen tinh tung doan (piecewise linear
interpolation), mot ky thuat toan hoc co ban.
"""

from dataclasses import dataclass, field


@dataclass
class AxisCalibration:
    """Hieu chuan 1 truc (X hoac Y): danh sach cac 'vach chia' (breakpoint),
    moi vach la 1 cap (pixel_pos, mm_pos) DA TICH LUY (khong phai do dai tung
    doan rieng le) - vach dau tien luon la (0, 0)."""

    # pixel_positions[i] va mm_positions[i] la vi tri TICH LUY cua vach thu i,
    # tinh tu goc truc (0 px = 0 mm). Danh sach phai tang dan (sau khi sap xep).
    pixel_positions: list = field(default_factory=lambda: [0.0])
    mm_positions: list = field(default_factory=lambda: [0.0])
    # Co RIENG danh dau da hieu chuan CHI TIET (nhieu doan, tu thuoc do overlay)
    # hay chua - KHONG duoc suy luan tu do dai danh sach, vi set_from_total()
    # cung tao ra danh sach 2 phan tu [0, total] giong het truong hop 1-doan don
    # gian mac dinh, nen phai phan biet bang co nay de tranh nham lan.
    is_custom: bool = False

    def is_default(self) -> bool:
        """True neu CHUA duoc nguoi dung hieu chuan chi tiet (van dang dung
        1 ty le don gian tu Rong/Cao phoi) - dung de quyet dinh co nen cho phep
        set_from_total() cap nhat lai theo Rong/Cao phoi moi hay khong."""
        return not self.is_custom

    def set_from_total(self, total_px: float, total_mm: float):
        """Thiet lap ve trang thai 1-doan don gian (giong hanh vi cu: 1 ty le
        duy nhat cho ca truc), dung khi nguoi dung chi nhap Rong/Cao phoi ma
        khong mo thuoc do chi tiet. KHONG danh dau la is_custom, de lan goi
        sau (vd nguoi dung sua lai Rong/Cao phoi) van tiep tuc cap nhat duoc."""
        self.pixel_positions = [0.0, max(1e-6, total_px)]
        self.mm_positions = [0.0, max(1e-6, total_mm)]
        self.is_custom = False

    def set_breakpoints(self, pixel_positions: list, mm_positions: list):
        """Thiet lap truc tiep danh sach vach chia (da sap xep tang dan theo
        pixel) TU NGUOI DUNG (thuoc do overlay) - danh dau is_custom=True de
        set_from_total() sau nay (khi Rong/Cao phoi doi) KHONG ghi de len nua."""
        if len(pixel_positions) != len(mm_positions) or len(pixel_positions) < 2:
            raise ValueError("Can it nhat 2 vach chia (diem dau va diem cuoi)")
        paired = sorted(zip(pixel_positions, mm_positions), key=lambda p: p[0])
        self.pixel_positions = [p[0] for p in paired]
        self.mm_positions = [p[1] for p in paired]
        self.is_custom = True

    def pixel_to_mm(self, px: float) -> float:
        """Quy doi 1 vi tri pixel (tinh tu goc truc) sang mm, noi suy tuyen tinh
        piecewise theo doan chua no; ngoai suy tuyen tinh neu nam ngoai pham vi
        da hieu chuan (dung do dai/ty le cua doan gan nhat)."""
        pts_px = self.pixel_positions
        pts_mm = self.mm_positions
        n = len(pts_px)

        if n < 2:
            # Chua co calibration nao (vd canvas moi khoi tao, chua tai anh) -
            # tra ve hang so duy nhat da co, tranh IndexError khi thuoc do
            # thuong truc ve truoc khi co anh/hieu chuan nao.
            return pts_mm[0] if pts_mm else 0.0

        if px <= pts_px[0]:
            i = 0
        elif px >= pts_px[-1]:
            i = n - 2
        else:
            i = 0
            for k in range(n - 1):
                if pts_px[k] <= px <= pts_px[k + 1]:
                    i = k
                    break

        px0, px1 = pts_px[i], pts_px[i + 1]
        mm0, mm1 = pts_mm[i], pts_mm[i + 1]
        span_px = px1 - px0
        if abs(span_px) < 1e-9:
            return mm0
        t = (px - px0) / span_px
        return mm0 + t * (mm1 - mm0)

    def mm_to_pixel(self, mm: float) -> float:
        """Chieu nguoc lai: tu mm ra vi tri pixel (can cho ve anh nen dung vi tri)."""
        pts_px = self.pixel_positions
        pts_mm = self.mm_positions
        n = len(pts_mm)

        if n < 2:
            return pts_px[0] if pts_px else 0.0

        if mm <= pts_mm[0]:
            i = 0
        elif mm >= pts_mm[-1]:
            i = n - 2
        else:
            i = 0
            for k in range(n - 1):
                if pts_mm[k] <= mm <= pts_mm[k + 1]:
                    i = k
                    break

        mm0, mm1 = pts_mm[i], pts_mm[i + 1]
        px0, px1 = pts_px[i], pts_px[i + 1]
        span_mm = mm1 - mm0
        if abs(span_mm) < 1e-9:
            return px0
        t = (mm - mm0) / span_mm
        return px0 + t * (px1 - px0)

    def total_mm(self) -> float:
        return self.mm_positions[-1]

    def total_px(self) -> float:
        return self.pixel_positions[-1]
