import docx
import os

# THAY ĐỔI TÊN FILE CỦA BẠN VÀO ĐÂY
file_name = "VN_-_Draft_MOU_on_China-Cambodia_AI_Application_Cooperation_Center_1.docx"

# Xây dựng đường dẫn tuyệt đối
file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', file_name)

print(f"Đang kiểm tra file tại đường dẫn: {file_path}")

if not os.path.exists(file_path):
    print(">>> KẾT QUẢ: LỖI! File không tồn tại ở đường dẫn trên.")
else:
    try:
        doc = docx.Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs if p.text])
        print(f">>> KẾT QUẢ: THÀNH CÔNG! Đọc được {len(text)} ký tự.")
        print("-" * 20)
        print(text[:500] + "...") # In ra 500 ký tự đầu tiên
        print("-" * 20)
    except Exception as e:
        print(f">>> KẾT QUẢ: LỖI! Không thể đọc file. Lỗi chi tiết: {e}")
