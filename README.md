# HỆ THỐNG QUẢN LÝ TÀI LIỆU

Đây là một ứng dụng web được xây dựng bằng Flask (Python) để quản lý, lưu trữ và tra cứu các tài liệu nước ngoài.

## Yêu cầu
- Ubuntu (hoặc các hệ điều hành Linux khác)
- Python 3.8+
- `git`

## Hướng dẫn Cài đặt

Mở Terminal và làm theo các bước sau:

**1. Tải mã nguồn về (Clone a repository):**
```bash
git clone <URL-CỦA-BẠN-TRÊN-GITHUB>
cd quan-ly-tai-lieu
```

Bước 2: Tạo và Kích hoạt Môi trường ảo
Đây là bước quan trọng để đảm bảo các gói thư viện của dự án không ảnh hưởng đến hệ thống chung.

```
# Tạo một môi trường ảo tên là 'venv'
python3 -m venv venv

# Kích hoạt môi trường ảo
source venv/bin/activate
```

Sau khi chạy lệnh trên, bạn sẽ thấy (venv) xuất hiện ở đầu dòng lệnh.

Bước 3: Cài đặt các Gói Thư viện cần thiết
Lệnh này sẽ tự động đọc file requirements.txt và cài đặt tất cả các thư viện cần thiết với đúng phiên bản.
pip install -r requirements.txt

Bước 4: Khởi tạo Cơ sở dữ liệu
Lệnh này chỉ cần chạy một lần duy nhất khi cài đặt lần đầu.

```
# Lệnh 1: Tạo các bảng trong database dựa trên file schema.sql
flask init-db

# Lệnh 2: Tạo tài khoản quản trị viên (admin) mặc định
flask create-admin
```

Bước 5: Chạy Ứng dụng

```flask run```


















