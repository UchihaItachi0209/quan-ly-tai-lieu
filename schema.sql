-- Xóa các bảng nếu chúng đã tồn tại để dễ dàng khởi tạo lại
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS documents;

-- Bảng người dùng
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    position TEXT, -- MỚI: Thêm cột chức vụ
    role TEXT NOT NULL DEFAULT 'user' -- 'admin' hoặc 'user'
);

-- Bảng tài liệu
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    authoring_agency TEXT,
    country TEXT,
    creation_date TEXT,
    source_type TEXT,
    confidentiality_level TEXT,
    urgency_level TEXT,
    original_file_path TEXT,
    translated_file_path TEXT,
    original_text TEXT,
    translated_text TEXT,
    main_content_summary TEXT,
    handler_id INTEGER,
    implementer_id INTEGER,
    completion_time TEXT,
    status TEXT NOT NULL DEFAULT 'Chưa xử lý',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (handler_id) REFERENCES users (id),
    FOREIGN KEY (implementer_id) REFERENCES users (id)
);
