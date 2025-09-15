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


app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'a_very_secret_key_for_session_management_v11_final'
app.config['DATABASE'] = os.path.join(app.instance_path, 'database.db')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(app.instance_path, exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ---------- DB helpers ----------
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

def ensure_schema():
    db = get_db()
    # documents extra cols
    dcols = [r[1] for r in db.execute("PRAGMA table_info(documents)").fetchall()]
    changed = False
    for col, ddl in [
        ('week_number',  "ALTER TABLE documents ADD COLUMN week_number INTEGER"),
        ('year_number',  "ALTER TABLE documents ADD COLUMN year_number INTEGER"),
        ('notes',        "ALTER TABLE documents ADD COLUMN notes TEXT"),
    ]:
        if col not in dcols:
            db.execute(ddl); changed = True

    # users avatar
    ucols = [r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()]
    if 'avatar' not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
        changed = True

    if changed: db.commit()

@app.before_request
def _ensure_schema_on_every_request():
    ensure_schema()

# ---------- time filters ----------
def _parse_dt(s):
    if not s: return None
    s = str(s).strip().replace('T', ' ').replace('Z', '')
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try: return datetime.strptime(s, fmt)
        except ValueError: pass
    try: return datetime.fromisoformat(s)
    except Exception: return None

@app.template_filter('vn_date')
def vn_date(s):
    dt = _parse_dt(s)
    if not dt: return s or ""
    has_time = not (dt.hour == 0 and dt.minute == 0 and dt.second == 0 and (" " not in str(s)))
    return dt.strftime("%d/%m/%Y %H:%M") if has_time else dt.strftime("%d/%m/%Y")

@app.template_filter('ymd')
def ymd(s):
    dt = _parse_dt(s)
    return dt.strftime("%Y-%m-%d") if dt else (s or "")

@app.template_filter('ymd_hm')
def ymd_hm(s):
    dt = _parse_dt(s)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else (s or "")

# ---------- utils ----------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def inner(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*a, **kw)
    return inner

def make_dicts(rows): return [dict(r) for r in rows]

def unique_secure_filename(filename: str) -> str:
    name, ext = os.path.splitext(secure_filename(filename))
    return f"{name}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"

def delete_file_safe(p):
    try:
        if p and os.path.exists(p): os.remove(p)
    except Exception: pass

def read_text_from_file(path):
    if not path or not os.path.exists(path): return ""
    try:
        if path.lower().endswith('.docx'):
            doc = docx.Document(path)
            return "\n".join([p.text for p in doc.paragraphs if p.text])
        if path.lower().endswith('.pdf'):
            out=""; 
            with fitz.open(path) as d:
                for page in d: out += page.get_text()
            return out
    except Exception as e:
        return f"Lỗi nghiêm trọng khi đọc file: {e}. Vui lòng kiểm tra lại file."
    return ""

def get_summary_from_gemini(text):
    if not text or "Lỗi" in text:
        return "Nội dung trống hoặc file lỗi, không thể tóm tắt."
    return f"[TÓM TẮT TỰ ĐỘNG (GIẢ LẬP)] {' '.join(text.split()[:50])}..."

# ---------- routes ----------
@app.route('/')
@login_required
def dashboard():
    db = get_db()
    stats = {
        "total":       db.execute('SELECT COUNT(id) FROM documents').fetchone()[0],
        "processing":  db.execute("SELECT COUNT(id) FROM documents WHERE status='Đang xử lý'").fetchone()[0],
        "completed":   db.execute("SELECT COUNT(id) FROM documents WHERE status='Đã xử lý'").fetchone()[0],
        "unassigned":  db.execute("SELECT COUNT(id) FROM documents WHERE status='Chưa xử lý'").fetchone()[0],
    }

    args = request.args
    q = (args.get('q') or '').strip()
    country = (args.get('country') or '').strip()
    status = (args.get('status') or '').strip()
    week_raw = (args.get('week') or '').strip()
    year_raw = (args.get('year') or '').strip()
    handler_raw = (args.get('handler_id') or '').strip()

    # chuẩn hóa
    week = ""
    if week_raw != "":
        try: week = f"{int(week_raw):02d}"
        except ValueError: week = ""
    year = ""
    if year_raw != "":
        try: year = f"{int(year_raw):04d}"
        except ValueError: year = ""

    try: page_size = int(args.get('page_size', 10))
    except ValueError: page_size = 10
    if page_size not in [5,10,20,50,100]: page_size = 10
    try: page = int(args.get('page', 1))
    except ValueError: page = 1
    if page < 1: page = 1

    cond, prm = [], []
    if q:       cond.append("d.title LIKE ?"); prm.append(f"%{q}%")
    if country: cond.append("d.country LIKE ?"); prm.append(f"%{country}%")
    if status:  cond.append("d.status = ?"); prm.append(status)
    if week:    cond.append("strftime('%W', d.creation_date) = ?"); prm.append(week)
    if year:    cond.append("strftime('%Y', d.creation_date) = ?"); prm.append(year)
    if handler_raw == 'null':
        cond.append("d.handler_id IS NULL")
    elif handler_raw:
        cond.append("d.handler_id = ?"); prm.append(int(handler_raw))
    where = "WHERE " + " AND ".join(cond) if cond else ""

    total_filtered = get_db().execute(f"SELECT COUNT(d.id) FROM documents d {where}", prm).fetchone()[0]
    total_pages = max((total_filtered + page_size - 1) // page_size, 1)
    if page > total_pages: page = total_pages
    offset = (page - 1) * page_size

    rows = db.execute(f"""
        SELECT d.*, u.full_name AS handler_name
        FROM documents d
        LEFT JOIN users u ON d.handler_id=u.id
        {where}
        ORDER BY d.created_at DESC
        LIMIT ? OFFSET ?
    """, (*prm, page_size, offset)).fetchall()

    users = make_dicts(db.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall())
    filters = {
        "q": q, "country": country, "status": status,
        "week": week, "year": year, "page_size": page_size,
        "handler_id": handler_raw,
    }
    return render_template(
        'index.html',
        stats=stats, documents=make_dicts(rows), users=users,
        current_user=session, active_page='documents',
        total_filtered=total_filtered, total_pages=total_pages, page=page, filters=filters
    )

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    db = get_db()
    uid = session['user_id']

    if request.method == 'POST':
        full_name = request.form.get('full_name','').strip()
        position  = request.form.get('position','').strip()
        new_pw    = request.form.get('new_password','').strip()
        confirm   = request.form.get('confirm_password','').strip()
        avatar_f  = request.files.get('avatar')

        # xử lý avatar
        avatar_rel = None
        if avatar_f and avatar_f.filename:
            os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'avatars'), exist_ok=True)
            fn = unique_secure_filename(avatar_f.filename)
            avatar_rel = os.path.join('avatars', fn)
            avatar_abs = os.path.join(app.config['UPLOAD_FOLDER'], avatar_rel)
            avatar_f.save(avatar_abs)

            old = db.execute("SELECT avatar FROM users WHERE id=?", (uid,)).fetchone()
            if old and old['avatar']:
                delete_file_safe(os.path.join(app.config['UPLOAD_FOLDER'], old['avatar']))

        # đổi mật khẩu (nếu có nhập)
        if new_pw or confirm:
            if new_pw != confirm:
                flash('Mật khẩu mới và xác nhận không khớp.', 'error')
                return redirect(url_for('profile'))
            db.execute("""
                UPDATE users SET full_name=?, position=?, avatar=COALESCE(?,avatar), password_hash=?
                WHERE id=?
            """, (full_name, position, avatar_rel, generate_password_hash(new_pw), uid))
        else:
            db.execute("""
                UPDATE users SET full_name=?, position=?, avatar=COALESCE(?,avatar)
                WHERE id=?
            """, (full_name, position, avatar_rel, uid))
        db.commit()

        session['user_name'] = full_name
        if avatar_rel: session['avatar'] = avatar_rel
        flash('Cập nhật hồ sơ thành công.', 'success')
        return redirect(url_for('profile'))

    user = db.execute("SELECT id, username, full_name, position, role, COALESCE(avatar,'') AS avatar FROM users WHERE id=?", (uid,)).fetchone()
    return render_template('index.html', profile_mode=True, user_profile=dict(user),
                           current_user=session, active_page='profile')

@app.route('/users')
@login_required
def manage_users():
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền truy cập trang này.', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    users = make_dicts(db.execute("SELECT id, username, full_name, role, position FROM users ORDER BY id ASC").fetchall())
    return render_template('users.html', users=users, current_user=session, active_page='users')

@app.route('/login', methods=['GET','POST'])
def login():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username, password = request.form['username'], request.form['password']
        db = get_db()
        u = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if u and check_password_hash(u['password_hash'], password):
            session.clear()
            session['user_id']=u['id']; session['user_role']=u['role']; session['user_name']=u['full_name']
            try: session['avatar']=u['avatar']
            except Exception: session['avatar']=''
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
    edit_mode = request.args.get('edit','false').lower()=='true'
    db = get_db()
    row = db.execute("""
        SELECT d.*, u.full_name AS handler_name
        FROM documents d
        LEFT JOIN users u ON d.handler_id=u.id
        WHERE d.id=?
    """, (doc_id,)).fetchone()
    if not row:
        flash('Không tìm thấy tài liệu.', 'error')
        return redirect(url_for('dashboard'))
    users = make_dicts(db.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall())
    return render_template('viewer.html', doc=dict(row), users=users,
                           current_user=session, edit_mode=edit_mode, active_page='documents')

@app.route('/uploads/<path:filename>')
@login_required
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# -------- Documents CRUD (giữ như bản trước) --------
@app.route('/documents/add', methods=['POST'])
@login_required
def add_document():
    db = get_db()
    f = request.form
    title = f['title']
    authoring_agency = f.get('authoring_agency')
    country = f.get('country')
    draft_time = f.get('creation_date')
    source_type = f.get('source_type')
    confidentiality_level = f.get('confidentiality_level')
    urgency_level = f.get('urgency_level')
    week_number = f.get('week_number') or None
    year_number = f.get('year_number') or None
    handler_id = f.get('handler_id')
    status = 'Đang xử lý' if handler_id and handler_id != "null" else 'Chưa xử lý'

    orig = request.files.get('original_file')
    tran = request.files.get('translated_file')

    def save_maybe(file):
        if not file or not file.filename: return None, ""
        p = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
        file.save(p)
        txt = read_text_from_file(p) if p.lower().endswith(('.pdf','.docx')) else ""
        return p, txt

    orig_path, orig_txt = save_maybe(orig)
    tran_path, tran_txt = save_maybe(tran)

    main_content = f.get('main_content') or ""
    notes = f.get('notes') or ""
    main_summary = (main_content.strip() or get_summary_from_gemini(tran_txt))

    db.execute("""
        INSERT INTO documents (
            title, authoring_agency, country, creation_date,
            source_type, confidentiality_level, urgency_level,
            original_file_path, translated_file_path,
            original_text, translated_text, main_content_summary,
            handler_id, status, week_number, year_number, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (title, authoring_agency, country, draft_time, source_type, confidentiality_level, urgency_level,
          orig_path, tran_path, orig_txt, tran_txt, main_summary,
          (handler_id if handler_id and handler_id!="null" else None),
          status, week_number, year_number, notes))
    db.commit()
    flash('Thêm tài liệu mới thành công!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/documents/<int:doc_id>/edit', methods=['POST'])
@login_required
def edit_document(doc_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error'); return redirect(url_for('dashboard'))
    f = request.form; db = get_db()
    handler_id = f.get('handler_id') if f.get('handler_id')!='null' else None
    status = f.get('status')
    completion_time = f.get('completion_time') or None
    main_content = f.get('main_content') or None
    notes = f.get('notes') or None
    db.execute("""
        UPDATE documents SET
          title=?, authoring_agency=?, country=?, creation_date=?,
          source_type=?, confidentiality_level=?, urgency_level=?,
          handler_id=?, status=?, completion_time=?, main_content_summary=?, notes=?
        WHERE id=?
    """, (f['title'], f['authoring_agency'], f['country'], f['creation_date'],
          f['source_type'], f['confidentiality_level'], f['urgency_level'],
          handler_id, status, completion_time, main_content, notes, doc_id))
    db.commit()
    flash('Cập nhật thông tin tài liệu thành công!', 'success')
    return redirect(url_for('view_document', doc_id=doc_id))

@app.route('/documents/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete_document(doc_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error'); return redirect(url_for('dashboard'))
    db = get_db()
    r = db.execute("SELECT original_file_path, translated_file_path FROM documents WHERE id=?", (doc_id,)).fetchone()
    if r:
        delete_file_safe(r['original_file_path']); delete_file_safe(r['translated_file_path'])
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,)); db.commit()
    flash('Đã xóa tài liệu thành công.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/documents/<int:doc_id>/report', methods=['POST'])
@login_required
def report_document(doc_id):
    db = get_db()
    db.execute("""
        UPDATE documents SET status='Đã xử lý', completion_time=?, implementer_id=?
        WHERE id=?
    """, (datetime.utcnow().isoformat(), session.get('user_id'), doc_id))
    db.commit()
    flash('Báo cáo hoàn thành thành công!', 'success')
    return redirect(url_for('view_document', doc_id=doc_id))

@app.route('/users/add', methods=['POST'])
@login_required
def add_user():
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    if f['password'] != f['confirm_password']:
        flash('Mật khẩu và xác nhận mật khẩu không khớp.', 'error'); return redirect(url_for('manage_users'))
    db = get_db()
    if db.execute("SELECT id FROM users WHERE username=?", (f['username'],)).fetchone():
        flash(f"Tên đăng nhập '{f['username']}' đã tồn tại.", "error"); return redirect(url_for('manage_users'))
    db.execute("""
        INSERT INTO users (username, password_hash, full_name, position, role)
        VALUES (?,?,?,?,?)
    """, (f['username'], generate_password_hash(f['password']), f['full_name'], f['position'], f['role']))
    db.commit()
    flash("Thêm người dùng mới thành công!", "success")
    return redirect(url_for('manage_users'))

@app.route('/users/<int:user_id>/edit', methods=['POST'])
@login_required
def edit_user(user_id):
    if session.get('user_role') != 'admin':
        flash('Bạn không có quyền.', 'error'); return redirect(url_for('dashboard'))
    f = request.form; db = get_db()
    if f.get('password'):
        if f['password'] != f.get('confirm_password',''):
            flash('Mật khẩu và xác nhận mật khẩu không khớp.', 'error'); return redirect(url_for('manage_users'))
        db.execute("""
            UPDATE users SET full_name=?, position=?, role=?, password_hash=? WHERE id=?
        """, (f['full_name'], f['position'], f['role'], generate_password_hash(f['password']), user_id))
    else:
        db.execute("""
            UPDATE users SET full_name=?, position=?, role=? WHERE id=?
        """, (f['full_name'], f['position'], f['role'], user_id))
    db.commit()
    flash("Cập nhật thông tin người dùng thành công!", "success")
    return redirect(url_for('manage_users'))

if __name__ == '__main__':
    app.run(debug=True)

