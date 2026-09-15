# GCode Vision

Phần mềm desktop soạn thảo và xem trước G-code cho gia công CNC, kèm khả năng nạp ảnh bản vẽ kỹ thuật làm nền tham chiếu để click chọn tọa độ trực tiếp trên ảnh.

Toàn bộ tính toán hình học, hiệu chỉnh tỷ lệ, phân tích G-code đều dùng thuật toán thuần túy (nội suy tuyến tính từng đoạn, lượng giác cơ bản) — **không dùng AI/ML**.

## Tính năng chính

- **Soạn thảo G-code** với tô màu cú pháp, tự động đánh số dòng (N), phím tắt chuẩn (Ctrl+S/O/N)
- **Xem trước đường chạy dao** theo thời gian thực trên canvas, hỗ trợ zoom/pan, snap lưới và snap vào các điểm G-code đã có sẵn
- **Nạp ảnh bản vẽ tham chiếu**, click trực tiếp lên ảnh để chèn tọa độ X/Y vào chương trình (hỗ trợ cả hệ tuyệt đối G90 và tương đối G91, tự động tính lại tọa độ khi đổi qua lại giữa 2 hệ)
- **Thước đo hiệu chỉnh (ruler calibration)** thường trực ở cạnh trên/trái canvas — chia bản vẽ thành nhiều đoạn với tỷ lệ px/mm riêng từng đoạn (piecewise), xử lý trường hợp ảnh chụp/scan có vùng kích thước không đồng nhất
- **Công cụ đo khoảng cách/góc tạm thời**, không ảnh hưởng đến G-code
- **Danh sách điểm** đã chèn trong chương trình, click để nhảy nhanh tới dòng tương ứng
- **Kiểm tra an toàn**: cảnh báo tọa độ ngoài vùng phôi, cảnh báo thiếu tốc độ F trước lệnh cắt, cảnh báo thiếu tham số I/J cho cung tròn, chặn chèn tọa độ ra ngoài phôi
- **Ước tính thời gian gia công** dựa trên tổng chiều dài đường chạy và tốc độ F khai báo
- **Tự động lưu bản nháp** mỗi 30 giây, khôi phục sau khi ứng dụng bị đóng đột ngột
- **Lịch sử phiên bản file**: tự sao lưu bản cũ mỗi lần ghi đè
- Chế độ tối, UI scale, xuất bản cài đặt Windows (.exe)

## Cài đặt

```bash
pip install -r requirements.txt
```

Yêu cầu Python 3.9+.

## Chạy ứng dụng

```bash
python3 run.py
```

## Cấu trúc dự án

```
├── run.py                     # điểm khởi chạy
├── requirements.txt
├── gcode_vision/               # package mã nguồn chính
│   ├── main_window.py          # cửa sổ chính, toàn bộ logic giao diện
│   ├── canvas_widget.py        # vùng vẽ xem trước đường chạy dao
│   ├── gcode_editor.py         # editor G-code (tô màu, auto-N)
│   ├── gcode_parser.py         # parser G-code thuần túy, không AI/ML
│   ├── ruler_calibration.py    # hiệu chuẩn tỷ lệ px/mm theo từng đoạn (piecewise)
│   └── ruler_dialog.py         # thước đo thường trực, tương tác kéo/nhập mm
├── assets/                     # logo
├── examples/                   # file G-code mẫu
├── installer_scripts/          # script Inno Setup để đóng gói .exe
└── .github/workflows/          # CI build Windows qua GitHub Actions
```

## Đóng gói bản cài đặt Windows

CI tự động build khi push lên `master`/`main` (xem `.github/workflows/build.yml`), tạo ra:
- Bản portable `.exe` (PyInstaller)
- Bộ cài đặt `.exe` có bảo vệ mật khẩu (Inno Setup)

Có thể build thủ công trên Windows:

```powershell
pyinstaller --noconfirm --onefile --windowed --name "GCode-Vision" --icon "assets\logo.ico" run.py
iscc installer_scripts\installer.iss
```

## Quy ước hệ tọa độ

Gốc (0,0) nằm ở góc **dưới-trái** vùng vẽ, trục Y hướng **lên** (giống bản vẽ cơ khí/CNC thực tế), khác với hệ tọa độ màn hình mặc định của Qt.

Khi nạp ảnh tham chiếu: crop ảnh cho khớp khung phôi, nhập Rộng/Cao phôi (mm) và offset a(X), a(Y) từ góc dưới-trái ảnh tới gốc tọa độ gia công thật. Nếu bản vẽ có vùng kích thước không đúng tỷ lệ đều, dùng thước đo ở cạnh trên/trái canvas để chia thành nhiều đoạn hiệu chỉnh riêng.
