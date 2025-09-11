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


# =========================
# CẤU HÌNH ỨNG DỤNG
# =========================
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'a_very_secret_key_for_session_management_v11_final'
app.config['DATABASE'] = os.path.join(app.instance_path, 'database.db')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')

for folder in [app.instance_path, app.config['UPLOAD_FOLDER']]:
    os.makedirs(folder, exist_ok=True)


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
    stats = {
        "total":        db.execute('SELECT COUNT(id) FROM documents').fetchone()[0],
        "processing":   db.execute("SELECT COUNT(id) FROM documents WHERE status = 'Đang xử lý'").fetchone()[0],
        "completed":    db.execute("SELECT COUNT(id) FROM documents WHERE status = 'Đã xử lý'").fetchone()[0],
        "unassigned":   db.execute("SELECT COUNT(id) FROM documents WHERE status = 'Chưa xử lý'").fetchone()[0],
    }
    documents_rows = db.execute("""
        SELECT d.*, u_handler.full_name as handler_name
        FROM documents d
        LEFT JOIN users u_handler ON d.handler_id = u_handler.id
        ORDER BY d.created_at DESC
    """).fetchall()
    documents = make_dicts(documents_rows)
    users = make_dicts(db.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall())
    return render_template('index.html', stats=stats, documents=documents, users=users,
                           current_user=session, active_page='dashboard')


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
    original_file = request.files.get('original_file')
    translated_file = request.files.get('translated_file')

    handler_id = data.get('handler_id')
    status = 'Đang xử lý' if handler_id and handler_id != "null" else 'Chưa xử lý'

    original_filepath, translated_filepath = None, None
    original_text, translated_text, summary = "", "", ""

    if original_file and original_file.filename:
        fname = unique_secure_filename(original_file.filename)
        original_filepath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        original_file.save(original_filepath)
        original_text = read_text_from_file(original_filepath)

    if translated_file and translated_file.filename:
        fname = unique_secure_filename(translated_file.filename)
        translated_filepath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        translated_file.save(translated_filepath)
        translated_text = read_text_from_file(translated_filepath)
        summary = get_summary_from_gemini(translated_text)

    db.execute("""
        INSERT INTO documents (
            title, authoring_agency, country, creation_date, source_type,
            confidentiality_level, urgency_level, original_file_path,
            translated_file_path, original_text, translated_text, main_content_summary,
            handler_id, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data['title'], data['authoring_agency'], data['country'], data['creation_date'],
        data['source_type'], data['confidentiality_level'], data['urgency_level'],
        original_filepath, translated_filepath, original_text, translated_text, summary,
        handler_id if handler_id != "null" else None, status
    ))
    db.commit()
    flash('Thêm tài liệu mới thành công!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/documents/<int:doc_id>/edit', methods=['POST'])
@login_required
def edit_document(doc_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error')
        return redirect(url_for('dashboard'))

    db = get_db()
    cur = db.execute("""
        SELECT original_file_path, translated_file_path
        FROM documents WHERE id = ?
    """, (doc_id,)).fetchone()
    if not cur:
        flash('Không tìm thấy tài liệu.', 'error')
        return redirect(url_for('dashboard'))

    form = request.form
    files = request.files

    handler_id = form.get('handler_id') if form.get('handler_id') != 'null' else None
    status = form.get('status')

    original_path = cur['original_file_path']
    translated_path = cur['translated_file_path']

    original_text = None
    translated_text = None
    summary = None

    # ORIGINAL
    if form.get('remove_original') == '1':
        delete_file_safe(original_path)
        original_path = None
        original_text = ""

    new_orig = files.get('original_file')
    if new_orig and new_orig.filename:
        fname = unique_secure_filename(new_orig.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        new_orig.save(save_path)
        original_path = save_path
        original_text = read_text_from_file(save_path)

    # TRANSLATED
    if form.get('remove_translated') == '1':
        delete_file_safe(translated_path)
        translated_path = None
        translated_text = ""
        summary = ""

    new_tr = files.get('translated_file')
    if new_tr and new_tr.filename:
        fname = unique_secure_filename(new_tr.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        new_tr.save(save_path)
        translated_path = save_path
        translated_text = read_text_from_file(save_path)
        summary = get_summary_from_gemini(translated_text)

    # UPDATE
    db.execute("""
        UPDATE documents SET
            title = ?, authoring_agency = ?, country = ?, creation_date = ?,
            source_type = ?, confidentiality_level = ?, urgency_level = ?,
            handler_id = ?, status = ?,
            original_file_path = ?, translated_file_path = ?,
            original_text = COALESCE(?, original_text),
            translated_text = COALESCE(?, translated_text),
            main_content_summary = COALESCE(?, main_content_summary)
        WHERE id = ?
    """, (
        form['title'], form['authoring_agency'], form['country'], form['creation_date'],
        form['source_type'], form['confidentiality_level'], form['urgency_level'],
        handler_id, status,
        original_path, translated_path,
        original_text, translated_text, summary,
        doc_id
    ))
    db.commit()

    flash('Cập nhật thông tin tài liệu thành công!', 'success')
    # ✅ Sau khi lưu, chuyển về chế độ XEM (không còn ?edit=true)
    return redirect(url_for('view_document', doc_id=doc_id))  # trở lại chế độ sửa để thấy ngay file mới


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

