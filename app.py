import os
import sqlite3
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, g, session, redirect,
    url_for, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import docx
import fitz  # PyMuPDF

from datetime import datetime



# =========================
# CẤU HÌNH ỨNG DỤNG
# =========================
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'a_very_secret_key_for_session_management_v11_final'
app.config['DATABASE'] = os.path.join(app.instance_path, 'database.db')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')

for folder in [app.instance_path, app.config['UPLOAD_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

# --- BẢO ĐẢM LƯỢC ĐỒ (thêm cột nếu chưa có) ---
def ensure_schema():
    db = get_db()
    cols = [r[1] for r in db.execute("PRAGMA table_info(documents)").fetchall()]
    changed = False
    if 'week_number' not in cols:
        db.execute("ALTER TABLE documents ADD COLUMN week_number INTEGER")
        changed = True
    if 'year_number' not in cols:
        db.execute("ALTER TABLE documents ADD COLUMN year_number INTEGER")
        changed = True
    if 'notes' not in cols:
        db.execute("ALTER TABLE documents ADD COLUMN notes TEXT")
        changed = True
    if changed:
        db.commit()

@app.before_request
def _ensure_schema_on_every_request():
    # Nhẹ, chỉ chạy ALTER khi thiếu cột
    ensure_schema()
    
def _parse_dt(s):
    if not s:
        return None
    s = str(s).strip()
    s = s.replace('T', ' ').replace('Z', '')
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

@app.template_filter('vn_date')
def vn_date(s):
    """Hiển thị dd/mm/yyyy hoặc dd/mm/yyyy HH:MM (24h)."""
    dt = _parse_dt(s)
    if not dt:
        return s or ""
    # nếu không có phần giờ trong nguồn (chỉ có ngày)
    has_time = not (dt.hour == 0 and dt.minute == 0 and dt.second == 0 and (" " not in str(s)))
    return dt.strftime("%d/%m/%Y %H:%M") if has_time else dt.strftime("%d/%m/%Y")

@app.template_filter('ymd')
def ymd(s):
    """Chuẩn hóa về YYYY-MM-DD cho Flatpickr date."""
    dt = _parse_dt(s)
    return dt.strftime("%Y-%m-%d") if dt else (s or "")

@app.template_filter('ymd_hm')
def ymd_hm(s):
    """Chuẩn hóa về YYYY-MM-DD HH:MM cho Flatpickr datetime."""
    dt = _parse_dt(s)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else (s or "")
    
# =========================
# TIỆN ÍCH CƠ SỞ DỮ LIỆU
# =========================
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.cli.command('init-db')
def init_db_command():
    db = get_db()
    with app.open_resource('schema.sql') as f:
        db.executescript(f.read().decode('utf8'))
    print('Initialized the database.')


@app.cli.command("create-admin")
def create_admin_command():
    username, password, full_name, position = "admin", "admin", "Quản trị viên", "System Admin"
    db = get_db()
    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        print(f"Người dùng '{username}' đã tồn tại.")
        return
    db.execute(
        "INSERT INTO users (username, password_hash, full_name, position, role) VALUES (?, ?, ?, ?, 'admin')",
        (username, generate_password_hash(password), full_name, position),
    )
    db.commit()
    print(f"Đã tạo tài khoản admin thành công! Tên đăng nhập: {username}, Mật khẩu: {password}")


# =========================
# TIỆN ÍCH CHUNG
# =========================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def make_dicts(rows):
    return [dict(ix) for ix in rows]


def unique_secure_filename(filename: str) -> str:
    """Tránh đè file khi trùng tên"""
    name, ext = os.path.splitext(secure_filename(filename))
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return f"{name}_{ts}{ext}"


def delete_file_safe(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        app.logger.warning(f"Could not delete file {path}: {e}")


def read_text_from_file(filepath):
    """Đọc text từ pdf/docx (đơn giản để demo)"""
    if not filepath or not os.path.exists(filepath):
        return ""
    text_content = ""
    try:
        if filepath.lower().endswith('.docx'):
            doc = docx.Document(filepath)
            text_content = "\n".join([p.text for p in doc.paragraphs if p.text])
        elif filepath.lower().endswith('.pdf'):
            with fitz.open(filepath) as doc:
                for page in doc:
                    text_content += page.get_text()
    except Exception as e:
        print(f"ERROR reading file {filepath}: {e}")
        return f"Lỗi nghiêm trọng khi đọc file: {e}. Vui lòng kiểm tra lại file."
    return text_content


def get_summary_from_gemini(text):
    if not text or "Lỗi" in text:
        return "Nội dung trống hoặc file lỗi, không thể tóm tắt."
    return f"[TÓM TẮT TỰ ĐỘNG (GIẢ LẬP)] {' '.join(text.split()[:50])}..."


# =========================
# ROUTES HIỂN THỊ
# =========================
@app.route('/')
@login_required
def dashboard():
    db = get_db()

    # Stats tổng quan
    stats = {
        "total": db.execute('SELECT COUNT(id) FROM documents').fetchone()[0],
        "processing": db.execute("SELECT COUNT(id) FROM documents WHERE status = 'Đang xử lý'").fetchone()[0],
        "completed": db.execute("SELECT COUNT(id) FROM documents WHERE status = 'Đã xử lý'").fetchone()[0],
        "unassigned": db.execute("SELECT COUNT(id) FROM documents WHERE status = 'Chưa xử lý'").fetchone()[0]
    }

    # ---- Lọc / tìm kiếm / phân trang ----
    args = request.args
    q = (args.get('q') or '').strip()                   # tìm theo Tiêu đề
    country = (args.get('country') or '').strip()       # Hướng (quốc gia)
    status = (args.get('status') or '').strip()         # Trạng thái
    week_raw = (args.get('week') or '').strip()         # Tuần (00-53)
    year_raw = (args.get('year') or '').strip()         # Năm (YYYY)

    # Chuẩn hoá week (2 chữ số, 00..53) & year (4 chữ số)
    week = ''
    if week_raw != '':
        try:
            week = f"{int(week_raw):02d}"
        except ValueError:
            week = ''
    year = ''
    if year_raw != '':
        try:
            year = f"{int(year_raw):04d}"
        except ValueError:
            year = ''

    # page size
    try:
        page_size = int(args.get('page_size', 10))
    except ValueError:
        page_size = 10
    if page_size not in [5, 10, 20, 50, 100]:
        page_size = 10

    # current page
    try:
        page = int(args.get('page', 1))
    except ValueError:
        page = 1
    if page < 1:
        page = 1

    # WHERE linh hoạt
    conditions, params = [], []
    if q:
        conditions.append("d.title LIKE ?")
        params.append(f"%{q}%")
    if country:
        conditions.append("d.country LIKE ?")
        params.append(f"%{country}%")
    if status:
        conditions.append("d.status = ?")
        params.append(status)
    if week:
        # Tuần theo SQLite: %W (Mon-first, 00..53)
        conditions.append("strftime('%W', d.creation_date) = ?")
        params.append(week)
    if year:
        conditions.append("strftime('%Y', d.creation_date) = ?")
        params.append(year)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    # Đếm & phân trang
    total_filtered = db.execute(
        f"SELECT COUNT(d.id) FROM documents d {where_clause}",
        params
    ).fetchone()[0]
    total_pages = max((total_filtered + page_size - 1) // page_size, 1)
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * page_size

    # Lấy danh sách
    rows = db.execute(f"""
        SELECT d.*, u_handler.full_name AS handler_name
        FROM documents d
        LEFT JOIN users u_handler ON d.handler_id = u_handler.id
        {where_clause}
        ORDER BY d.created_at DESC
        LIMIT ? OFFSET ?
    """, (*params, page_size, offset)).fetchall()

    documents = make_dicts(rows)
    users = make_dicts(db.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall())

    filters = {
        "q": q, "country": country, "status": status,
        "week": week, "year": year, "page_size": page_size
    }

    return render_template(
        'index.html',
        stats=stats,
        documents=documents,
        users=users,
        current_user=session,
        active_page='dashboard',
        total_filtered=total_filtered,
        total_pages=total_pages,
        page=page,
        filters=filters
    )




@app.route('/users')
@login_required
def manage_users():
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền truy cập trang này.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    users = make_dicts(db.execute("SELECT id, username, full_name, role, position FROM users ORDER BY id ASC").fetchall())
    return render_template('users.html', users=users, current_user=session, active_page='users')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'], session['user_role'], session['user_name'] = user['id'], user['role'], user['full_name']
            return redirect(url_for('dashboard'))
        flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Bạn đã đăng xuất.', 'info')
    return redirect(url_for('login'))


@app.route('/document/<int:doc_id>')
@login_required
def view_document(doc_id):
    edit_mode = request.args.get('edit', 'false').lower() == 'true'
    db = get_db()
    doc_row = db.execute("""
        SELECT d.*, u_handler.full_name as handler_name
        FROM documents d
        LEFT JOIN users u_handler ON d.handler_id = u_handler.id
        WHERE d.id = ?
    """, (doc_id,)).fetchone()
    if doc_row is None:
        flash('Không tìm thấy tài liệu.', 'error')
        return redirect(url_for('dashboard'))
    doc = dict(doc_row)
    users = make_dicts(db.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall())
    return render_template('viewer.html', doc=doc, users=users, current_user=session,
                           edit_mode=edit_mode, active_page='documents')


@app.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# =========================
# FORM / API
# =========================
@app.route('/documents/add', methods=['POST'])
@login_required
def add_document():
    db = get_db()
    data = request.form

    # === Trường chính ===
    title = data['title']
    authoring_agency = data.get('authoring_agency')
    country = data.get('country')
    draft_time = data.get('creation_date')  # NHÃN hiển thị là "Thời gian soạn thảo"
    source_type = data.get('source_type')
    confidentiality_level = data.get('confidentiality_level')
    urgency_level = data.get('urgency_level')

    # Tuần/Năm tách rời, không liên quan ngày
    week_number = data.get('week_number') or None
    year_number = data.get('year_number') or None

    handler_id = data.get('handler_id')
    status = 'Đang xử lý' if handler_id and handler_id != "null" else 'Chưa xử lý'

    # === File upload (không bắt buộc, chấp nhận mọi loại; chỉ đọc text nếu pdf/docx) ===
    original_file = request.files.get('original_file')
    translated_file = request.files.get('translated_file')

    original_filepath = None
    translated_filepath = None
    original_text, translated_text = "", ""

    def save_and_maybe_extract(file_storage):
        if not file_storage or file_storage.filename == '':
            return None, ""
        safe_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file_storage.filename))
        file_storage.save(safe_path)
        # Chỉ trích xuất text với PDF/DOCX
        lower = safe_path.lower()
        if lower.endswith('.pdf') or lower.endswith('.docx'):
            try:
                return safe_path, read_text_from_file(safe_path)
            except Exception:
                return safe_path, ""
        return safe_path, ""

    original_filepath, original_text = save_and_maybe_extract(original_file)
    translated_filepath, translated_text = save_and_maybe_extract(translated_file)

    # “Nội dung chính” & “Ghi chú” (không bắt buộc)
    main_content = data.get('main_content') or ""
    notes = data.get('notes') or ""

    # Nếu chưa nhập “Nội dung chính” mà có bản dịch → tóm tắt tạm
    main_content_summary = main_content.strip() or get_summary_from_gemini(translated_text)

    db.execute(
        """
        INSERT INTO documents (
            title, authoring_agency, country, creation_date,
            source_type, confidentiality_level, urgency_level,
            original_file_path, translated_file_path,
            original_text, translated_text, main_content_summary,
            handler_id, status, week_number, year_number, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title, authoring_agency, country, draft_time,
            source_type, confidentiality_level, urgency_level,
            original_filepath, translated_filepath,
            original_text, translated_text, main_content_summary,
            (handler_id if handler_id and handler_id != "null" else None),
            status, week_number, year_number, notes
        )
    )
    db.commit()
    flash('Thêm tài liệu mới thành công!', 'success')
    return redirect(url_for('dashboard'))



@app.route('/documents/<int:doc_id>/edit', methods=['POST'])
@login_required
def edit_document(doc_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error')
        return redirect(url_for('dashboard'))

    data = request.form
    db = get_db()
    handler_id = data.get('handler_id') if data.get('handler_id') != 'null' else None
    status = data.get('status')
    completion_time = data.get('completion_time') or None  # định dạng "YYYY-MM-DD HH:MM" từ flatpickr
    main_content = data.get('main_content') or None
    notes = data.get('notes') or None

    db.execute(
        """UPDATE documents SET 
           title = ?, authoring_agency = ?, country = ?, creation_date = ?, 
           source_type = ?, confidentiality_level = ?, urgency_level = ?, 
           handler_id = ?, status = ?, completion_time = ?, 
           main_content_summary = ?, notes = ?
           WHERE id = ?""",
        (data['title'], data['authoring_agency'], data['country'], data['creation_date'],
         data['source_type'], data['confidentiality_level'], data['urgency_level'],
         handler_id, status, completion_time, main_content, notes, doc_id)
    )
    db.commit()
    flash('Cập nhật thông tin tài liệu thành công!', 'success')
    return redirect(url_for('view_document', doc_id=doc_id))  # quay về chế độ xem




@app.route('/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(doc_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    # xóa file thực trên đĩa (nếu muốn)
    row = db.execute("SELECT original_file_path, translated_file_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if row:
        delete_file_safe(row['original_file_path'])
        delete_file_safe(row['translated_file_path'])
    db.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    db.commit()
    flash('Đã xóa tài liệu thành công.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/documents/<int:doc_id>/report', methods=['POST'])
@login_required
def report_document(doc_id):
    completion_time, implementer_id = datetime.utcnow().isoformat(), session.get('user_id')
    db = get_db()
    db.execute("""
        UPDATE documents
        SET status = 'Đã xử lý', completion_time = ?, implementer_id = ?
        WHERE id = ?
    """, (completion_time, implementer_id, doc_id))
    db.commit()
    flash('Báo cáo hoàn thành thành công!', 'success')
    return redirect(url_for('view_document', doc_id=doc_id))


@app.route('/users/add', methods=['POST'])
@login_required
def add_user():
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error')
        return redirect(url_for('dashboard'))
    password = request.form['password']
    confirm_password = request.form['confirm_password']
    if password != confirm_password:
        flash('Mật khẩu và xác nhận mật khẩu không khớp.', 'error')
        return redirect(url_for('manage_users'))
    username = request.form['username']
    full_name, position, role = request.form['full_name'], request.form['position'], request.form['role']
    db = get_db()
    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        flash(f"Tên đăng nhập '{username}' đã tồn tại.", "error")
        return redirect(url_for('manage_users'))
    db.execute(
        "INSERT INTO users (username, password_hash, full_name, position, role) VALUES (?, ?, ?, ?, ?)",
        (username, generate_password_hash(password), full_name, position, role),
    )
    db.commit()
    flash("Thêm người dùng mới thành công!", "success")
    return redirect(url_for('manage_users'))


@app.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
def edit_user(user_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error')
        return redirect(url_for('dashboard'))
    full_name, position, role = request.form['full_name'], request.form['position'], request.form['role']
    password, confirm_password = request.form.get('password'), request.form.get('confirm_password')
    db = get_db()
    if password:
        if password != confirm_password:
            flash('Mật khẩu và xác nhận mật khẩu không khớp.', 'error')
            return redirect(url_for('manage_users'))
        password_hash = generate_password_hash(password)
        db.execute(
            "UPDATE users SET full_name = ?, position = ?, role = ?, password_hash = ? WHERE id = ?",
            (full_name, position, role, password_hash, user_id),
        )
    else:
        db.execute(
            "UPDATE users SET full_name = ?, position = ?, role = ? WHERE id = ?",
            (full_name, position, role, user_id),
        )
    db.commit()
    flash("Cập nhật thông tin người dùng thành công!", "success")
    return redirect(url_for('manage_users'))


@app.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    if int(user_id) == session.get('user_id'):
        flash('Không thể xóa tài khoản của chính bạn.', 'error')
        return redirect(url_for('manage_users'))
    db.execute('DELETE FROM users WHERE id = ?', (user_id,))
    db.commit()
    flash('Đã xóa người dùng thành công.', 'success')
    return redirect(url_for('manage_users'))


if __name__ == '__main__':
    app.run(debug=True)

