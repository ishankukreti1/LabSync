import os
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
import pymysql

from config import Config
from database import get_db_connection, init_db
import json
import subprocess
from pathlib import Path

# Flask calls the C++ bridge; all scheduling logic stays in C++.
PROJECT_ROOT = Path(__file__).resolve().parent

def run_cpp_scheduler():
    paths = [PROJECT_ROOT / 'build' / 'Release' / 'LabSyncBridge.exe',
             PROJECT_ROOT / 'build' / 'LabSyncBridge.exe',
             PROJECT_ROOT / 'build-release' / 'Release' / 'LabSyncBridge.exe',
             PROJECT_ROOT / 'build-release' / 'LabSyncBridge.exe']
    binary = next((p for p in paths if p.is_file()), None)
    if binary is None:
        return {'success': False, 'message': 'LabSyncBridge.exe not found. Build the LabSyncBridge CMake target first.'}
    env = os.environ.copy()
    env.update(MYSQL_HOST=str(Config.MYSQL_HOST), MYSQL_PORT=str(Config.MYSQL_PORT),
               MYSQL_USER=str(Config.MYSQL_USER), MYSQL_PASSWORD=str(Config.MYSQL_PASSWORD),
               MYSQL_DB=str(Config.MYSQL_DB))
    try:
        result = subprocess.run([str(binary), 'schedule'], cwd=str(PROJECT_ROOT), env=env,
                                capture_output=True, text=True, timeout=120, check=False)
        data = json.loads(result.stdout)
        if result.returncode != 0:
            data['success'] = False
        return data
    except subprocess.TimeoutExpired:
        return {'success': False, 'message': 'C++ scheduler timed out after 120 seconds.'}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {'success': False, 'message': f'C++ scheduler bridge error: {exc}'}


app = Flask(__name__)
app.config.from_object(Config)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Helper function to check password (supports both werkzeug hash & plain text legacy)
def verify_password(stored_password, provided_password):
    if not stored_password:
        return False
    if stored_password == provided_password:
        return True
    if stored_password.startswith(('scrypt:', 'pbkdf2:')):
        try:
            return check_password_hash(stored_password, provided_password)
        except Exception:
            return False
    return False

# Authentication decorators
def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'student':
            flash("Please log in as a student to access this page.", "warning")
            return redirect(url_for('login', role='student'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            flash("Admin credentials required to view this dashboard.", "warning")
            return redirect(url_for('login', role='admin'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_db_status():
    connected = False
    try:
        conn = get_db_connection()
        conn.close()
        connected = True
    except Exception:
        connected = False
    return dict(is_db_connected=connected)

@app.before_request
def check_database_ready():
    # Only try to init once if not already initialized
    if not getattr(app, '_db_initialized', False):
        try:
            init_db()
            app._db_initialized = True
        except Exception as e:
            if request.endpoint not in ('db_settings', 'static'):
                pass

# ==========================================
# PUBLIC ROUTES
# ==========================================

@app.route('/')
def index():
    db_connected = False
    stats = {"students": 0, "exams": 0, "labs": 0, "computers": 0}
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM students")
            stats['students'] = cur.fetchone()['total']
            cur.execute("SELECT COUNT(*) AS total FROM exams")
            stats['exams'] = cur.fetchone()['total']
            cur.execute("SELECT COUNT(*) AS total FROM labs")
            stats['labs'] = cur.fetchone()['total']
            cur.execute("SELECT COUNT(*) AS total FROM computers WHERE state='ACTIVE'")
            stats['computers'] = cur.fetchone()['total']
        conn.close()
        db_connected = True
    except Exception:
        db_connected = False

    return render_template('index.html', db_connected=db_connected, stats=stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    role = request.args.get('role', 'student')
    if request.method == 'POST':
        role = request.form.get('role', 'student')
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash("Please enter both email and password.", "error")
            return render_template('login.html', role=role)

        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                table = "admins" if role == "admin" else "students"
                id_col = "admin_id" if role == "admin" else "student_id"
                cur.execute(f"SELECT {id_col} AS id, name, email, password_hash FROM {table} WHERE email = %s", (email,))
                user = cur.fetchone()

            conn.close()

            if user and verify_password(user['password_hash'], password):
                session.clear()
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                session['user_email'] = user['email']
                session['role'] = role
                flash(f"🎉 Welcome back, {user['name']}!", "success")
                if role == 'admin':
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('student_dashboard'))
            else:
                flash("Invalid email or password. Please try again.", "error")

        except pymysql.err.OperationalError as e:
            if e.args and e.args[0] == 1045:
                flash("🔑 MySQL Access Denied: Please enter your MySQL root password below to connect to the database.", "warning")
                return redirect(url_for('db_settings'))
            flash(f"Database connection error: {str(e)}", "error")
        except Exception as e:
            flash(f"Database connection error: {str(e)}", "error")

    return render_template('login.html', role=role)

@app.route('/register', methods=['GET', 'POST'])
def register():
    role = request.args.get('role', 'student')
    if request.method == 'POST':
        role = request.form.get('role', 'student')
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not name or not email or not password:
            flash("Please fill in all required fields.", "error")
            return render_template('register.html', role=role)

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template('register.html', role=role)

        password_hash = generate_password_hash(password)

        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                table = "admins" if role == "admin" else "students"
                id_col = "admin_id" if role == "admin" else "student_id"

                # Check duplicate email
                cur.execute(f"SELECT {id_col} FROM {table} WHERE email = %s", (email,))
                if cur.fetchone():
                    flash(f"An account with email '{email}' already exists. Please log in.", "warning")
                    conn.close()
                    return redirect(url_for('login', role=role))

                cur.execute(
                    f"INSERT INTO {table} (name, email, password_hash) VALUES (%s, %s, %s)",
                    (name, email, password_hash)
                )
                new_id = cur.lastrowid

            conn.close()
            role_label = "Student" if role == "student" else "Admin"
            flash(f"✨ {role_label} account created successfully! Please log in.", "success")
            return redirect(url_for('login', role=role))

        except pymysql.err.OperationalError as e:
            if e.args and e.args[0] == 1045:
                flash("🔑 MySQL Access Denied: Please enter your MySQL root password below to connect to the database.", "warning")
                return redirect(url_for('db_settings'))
            flash(f"Database error: {str(e)}", "error")
        except Exception as e:
            flash(f"Registration error: {str(e)}", "error")

    return render_template('register.html', role=role)

@app.route('/logout')
def logout():
    name = session.get('user_name', 'there')
    session.clear()
    flash(f"Goodbye, {name}! You have been signed out.", "info")
    return redirect(url_for('index'))

@app.route('/settings/database', methods=['GET', 'POST'])
def db_settings():
    if request.method == 'POST':
        host = request.form.get('host', '127.0.0.1').strip()
        port = int(request.form.get('port', Config.MYSQL_PORT))
        user = request.form.get('user', 'root').strip()
        form_pw = request.form.get('password', '').strip()
        password = form_pw if form_pw else Config.MYSQL_PASSWORD
        database = request.form.get('database', 'labsync').strip()

        Config.save(host, port, user, password, database)

        try:
            init_db()
            app._db_initialized = True
            flash("✅ Connected to MySQL successfully! Database initialized.", "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Connection test failed: {str(e)}", "error")

    return render_template('db_settings.html', config=Config)

# ==========================================
# STUDENT PORTAL ROUTES
# ==========================================

@app.route('/student/dashboard')
@student_required
def student_dashboard():
    sid = session['user_id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Fetch student info
            cur.execute("SELECT student_id, name, email FROM students WHERE student_id = %s", (sid,))
            student = cur.fetchone()

            # 2. Fetch available exams with their slots
            cur.execute("""
                SELECT e.exam_id, e.exam_name, e.subject_code, e.exam_date, e.priority AS exam_priority,
                       s.slot_id, s.start_time, s.end_time, s.capacity,
                       (SELECT COUNT(*) FROM allocations a WHERE a.slot_id = s.slot_id AND a.status = 'ALLOCATED') AS allocated_count
                FROM exams e
                JOIN slots s ON s.exam_id = e.exam_id
                ORDER BY e.exam_date ASC, s.start_time ASC
            """)
            slots_data = cur.fetchall()

            # 3. Fetch student's bookings
            cur.execute("""
                SELECT r.request_id, r.priority, r.request_time, r.status,
                       e.exam_name, e.subject_code, e.exam_date,
                       s.start_time, s.end_time,
                       l.lab_name, c.computer_no
                FROM requests r
                JOIN exams e ON e.exam_id = r.exam_id
                JOIN slots s ON s.slot_id = r.slot_id
                LEFT JOIN allocations a ON a.request_id = r.request_id AND a.status = 'ALLOCATED'
                LEFT JOIN computers c ON c.computer_id = a.computer_id
                LEFT JOIN labs l ON l.lab_id = c.lab_id
                WHERE r.student_id = %s
                ORDER BY r.request_time DESC
            """, (sid,))
            my_bookings = cur.fetchall()

        return render_template(
            'student_dashboard.html',
            student=student,
            slots=slots_data,
            bookings=my_bookings
        )
    finally:
        conn.close()


@app.route('/student/book', methods=['POST'])
@student_required
def book_slot():
    sid = session['user_id']
    slot_id = request.form.get('slot_id')

    if not slot_id:
        flash("Please select an exam slot to book.", "error")
        return redirect(url_for('student_dashboard'))

    conn = get_db_connection()

    try:
        with conn.cursor() as cur:

            # Step 1: Get exam details for selected slot
            cur.execute("""
                SELECT s.exam_id, e.priority
                FROM slots s
                JOIN exams e ON e.exam_id = s.exam_id
                WHERE s.slot_id = %s
            """, (slot_id,))

            slot = cur.fetchone()

            if not slot:
                flash("Selected slot does not exist.", "error")
                return redirect(url_for('student_dashboard'))

            exam_id = slot['exam_id']
            priority = slot.get('priority', 2)

            # Step 2: Prevent duplicate or completed exam bookings
            cur.execute("""
                SELECT status
                FROM requests
                WHERE student_id = %s
                  AND exam_id = %s
                  AND status IN (
                      'READY',
                      'WAITING',
                      'ALLOCATED',
                      'COMPLETED'
                  )
                LIMIT 1
            """, (sid, exam_id))

            existing = cur.fetchone()

            if existing:
                if existing['status'] == 'COMPLETED':
                    flash(
                        "You have already completed this exam. "
                        "You cannot book it again.",
                        "error"
                    )
                else:
                    flash(
                        "You have already booked this exam.",
                        "warning"
                    )

                return redirect(url_for('student_dashboard'))

            # Step 3: Create new booking request
            cur.execute("""
                INSERT INTO requests
                    (student_id, exam_id, slot_id, priority, status)
                VALUES (%s, %s, %s, %s, 'READY')
            """, (sid, exam_id, slot_id, priority))

            req_id = cur.lastrowid

        conn.commit()

        flash(
            f"Exam slot booked successfully "
            f"(Request #{req_id})! "
            "It is queued for desk allocation.",
            "success"
        )

    except Exception as e:
        conn.rollback()
        flash(f"Booking failed: {str(e)}", "error")

    finally:
        conn.close()

    return redirect(url_for('student_dashboard'))


@app.route('/student/cancel/<int:request_id>', methods=['POST'])
@student_required
def cancel_booking(request_id):
    sid = session['user_id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check ownership and cancellable status
            cur.execute("""
                SELECT request_id, status FROM requests
                WHERE request_id = %s AND student_id = %s
                AND status IN ('READY', 'WAITING', 'ALLOCATED')
            """, (request_id, sid))
            req = cur.fetchone()

            if not req:
                flash("Booking could not be cancelled or was already completed.", "error")
                return redirect(url_for('student_dashboard'))

            # Cancel allocation if exists
            cur.execute("""
                UPDATE allocations SET status = 'CANCELLED'
                WHERE request_id = %s AND status = 'ALLOCATED'
            """, (request_id,))

            # Cancel request
            cur.execute("""
                UPDATE requests SET status = 'CANCELLED'
                WHERE request_id = %s
            """, (request_id,))

        flash("Booking cancelled successfully.", "info")
    except Exception as e:
        flash(f"Cancellation failed: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('student_dashboard'))

# ==========================================
# ADMIN PORTAL ROUTES
# ==========================================

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Overview counters
            cur.execute("SELECT COUNT(*) AS total FROM students")
            total_students = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM exams")
            total_exams = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM labs")
            total_labs = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM computers")
            total_pcs = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM requests WHERE status IN ('READY', 'WAITING')")
            pending_requests = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM allocations WHERE status = 'ALLOCATED'")
            active_allocations = cur.fetchone()['total']

            # Exams list
            cur.execute("SELECT * FROM exams ORDER BY exam_date DESC")
            exams = cur.fetchall()

            # Slots list
            cur.execute("""
                SELECT s.slot_id, s.exam_id, s.start_time, s.end_time, s.capacity,
                       e.exam_name, e.subject_code,
                       (SELECT COUNT(*) FROM allocations a WHERE a.slot_id = s.slot_id AND a.status = 'ALLOCATED') AS current_allocated
                FROM slots s
                JOIN exams e ON e.exam_id = s.exam_id
                ORDER BY e.exam_date DESC, s.start_time ASC
            """)
            slots = cur.fetchall()

            # Labs list with PC counts
            cur.execute("""
                SELECT l.lab_id, l.lab_name, l.capacity,
                       COUNT(c.computer_id) AS total_computers,
                       SUM(CASE WHEN c.state = 'ACTIVE' THEN 1 ELSE 0 END) AS active_computers,
                       SUM(CASE WHEN c.state = 'MAINTENANCE' THEN 1 ELSE 0 END) AS maintenance_computers
                FROM labs l
                LEFT JOIN computers c ON c.lab_id = l.lab_id
                GROUP BY l.lab_id, l.lab_name, l.capacity
                ORDER BY l.lab_id ASC
            """)
            labs = cur.fetchall()

            # All bookings & requests
            cur.execute("""
                SELECT r.request_id, r.priority, r.request_time, r.status,
                       st.student_id, st.name AS student_name, st.email AS student_email,
                       e.exam_name, e.subject_code,
                       s.slot_id, s.start_time, s.end_time,
                       l.lab_name, c.computer_no
                FROM requests r
                JOIN students st ON st.student_id = r.student_id
                JOIN exams e ON e.exam_id = r.exam_id
                JOIN slots s ON s.slot_id = r.slot_id
                LEFT JOIN allocations a ON a.request_id = r.request_id AND a.status = 'ALLOCATED'
                LEFT JOIN computers c ON c.computer_id = a.computer_id
                LEFT JOIN labs l ON l.lab_id = c.lab_id
                ORDER BY r.request_time DESC
            """)
            all_bookings = cur.fetchall()

            # PC Availability Matrix by Lab
            cur.execute("""
                SELECT c.computer_id, c.computer_no, c.state, l.lab_id, l.lab_name
                FROM computers c
                JOIN labs l ON l.lab_id = c.lab_id
                ORDER BY l.lab_id ASC, c.computer_id ASC
            """)
            all_computers = cur.fetchall()

            # Registered Students Directory with metrics
            cur.execute("""
                SELECT s.student_id, s.name, s.email,
                       COUNT(r.request_id) AS total_bookings,
                       SUM(CASE WHEN r.status = 'ALLOCATED' THEN 1 ELSE 0 END) AS active_allocations,
                       SUM(CASE WHEN r.status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_exams
                FROM students s
                LEFT JOIN requests r ON r.student_id = s.student_id
                GROUP BY s.student_id, s.name, s.email
                ORDER BY s.student_id ASC
            """)
            registered_students = cur.fetchall()

        stats = {
            "students": total_students,
            "exams": total_exams,
            "labs": total_labs,
            "computers": total_pcs,
            "pending": pending_requests,
            "allocated": active_allocations
        }

        return render_template(
            'admin_dashboard.html',
            stats=stats,
            exams=exams,
            slots=slots,
            labs=labs,
            bookings=all_bookings,
            computers=all_computers,
            students=registered_students
        )
    finally:
        conn.close()

# Admin Actions

@app.route('/admin/exam/add', methods=['POST'])
@admin_required
def add_exam():
    name = request.form.get('exam_name', '').strip()
    code = request.form.get('subject_code', '').strip()
    date = request.form.get('exam_date', '').strip()
    priority = int(request.form.get('priority', 2))

    if not name or not code or not date:
        flash("Please provide exam name, subject code, and date.", "error")
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO exams (exam_name, subject_code, exam_date, priority)
                VALUES (%s, %s, %s, %s)
            """, (name, code, date, priority))
        flash(f"✅ Exam '{name}' added successfully!", "success")
    except Exception as e:
        flash(f"Failed to add exam: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/slot/add', methods=['POST'])
@admin_required
def add_slot():
    exam_id = request.form.get('exam_id')
    start_time = request.form.get('start_time', '').strip()
    end_time = request.form.get('end_time', '').strip()
    capacity = int(request.form.get('capacity', 30))

    if not exam_id or not start_time or not end_time or capacity <= 0:
        flash("Please provide valid exam, time, and positive capacity.", "error")
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO slots (exam_id, start_time, end_time, capacity)
                VALUES (%s, %s, %s, %s)
            """, (exam_id, start_time, end_time, capacity))
        flash(f"✅ Slot ({start_time} - {end_time}) added successfully!", "success")
    except Exception as e:
        flash(f"Failed to add slot: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/lab/add', methods=['POST'])
@admin_required
def add_lab():
    name = request.form.get('lab_name', '').strip()
    capacity = int(request.form.get('capacity', 30))

    if not name or capacity <= 0:
        flash("Please provide a valid lab name and positive capacity.", "error")
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO labs (lab_name, capacity)
                VALUES (%s, %s)
            """, (name, capacity))
            new_lab_id = cur.lastrowid
        flash(f"✅ Lab '{name}' created with Lab ID: {new_lab_id} (Capacity: {capacity})!", "success")
    except Exception as e:
        flash(f"Failed to add lab: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/computer/add-bulk', methods=['POST'])
@admin_required
def add_computers_bulk():
    lab_id = int(request.form.get('lab_id'))
    quantity = int(request.form.get('quantity', 1))

    if quantity <= 0 or quantity > 1000:
        flash("Quantity must be between 1 and 1000.", "error")
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check lab capacity & registered
            cur.execute("SELECT capacity, lab_name FROM labs WHERE lab_id = %s", (lab_id,))
            lab = cur.fetchone()
            if not lab:
                flash("Selected lab does not exist.", "error")
                return redirect(url_for('admin_dashboard'))

            cap = lab['capacity']
            cur.execute("SELECT COUNT(*) AS total FROM computers WHERE lab_id = %s", (lab_id,))
            registered = cur.fetchone()['total']

            if registered + quantity > cap:
                flash(f"Cannot add {quantity} PCs: Exceeds lab capacity ({registered}/{cap} already registered).", "error")
                return redirect(url_for('admin_dashboard'))

            added = 0
            cand = 1
            while added < quantity:
                # Format PC-001, PC-002...
                pc_no = f"PC-{cand:03d}"
                cur.execute("SELECT computer_id FROM computers WHERE lab_id = %s AND computer_no = %s", (lab_id, pc_no))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO computers (lab_id, computer_no, state) VALUES (%s, %s, 'ACTIVE')",
                        (lab_id, pc_no)
                    )
                    added += 1
                cand += 1

        flash(f"💻 Added {added} computers to {lab['lab_name']} successfully!", "success")
    except Exception as e:
        flash(f"Failed to add computers: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/computer/toggle-state/<int:computer_id>', methods=['POST'])
@admin_required
def toggle_computer_state(computer_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state, computer_no FROM computers WHERE computer_id = %s", (computer_id,))
            pc = cur.fetchone()
            if pc:
                new_state = 'MAINTENANCE' if pc['state'] == 'ACTIVE' else 'ACTIVE'
                cur.execute("UPDATE computers SET state = %s WHERE computer_id = %s", (new_state, computer_id))
                flash(f"🖥️ {pc['computer_no']} state changed to {new_state}.", "info")
    except Exception as e:
        flash(f"Error updating PC state: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/scheduler/run', methods=['POST'])
@admin_required
def trigger_scheduler():
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS total FROM requests "
                    "WHERE status IN ('READY', 'WAITING')"
                )
                pending = cur.fetchone()['total']
        finally:
            conn.close()

        if pending == 0:
            flash("✨ No pending requests to schedule.", "info")
            return redirect(url_for('admin_dashboard'))

        res = run_cpp_scheduler()

        if res.get('success'):
            alloc = res.get('allocated', 0)
            wait = res.get('waiting', 0)

            if alloc > 0:
                flash(
                    f"🚀 Scheduler completed: {alloc} student(s) allocated "
                    f"to desks, {wait} in waiting queue.",
                    "success"
                )
            elif wait > 0:
                flash(
                    f"⚠️ Scheduler ran: 0 allocated, {wait} students "
                    "placed in waiting list.",
                    "warning"
                )
            else:
                flash("✨ No pending requests in queue.", "info")
        else:
            flash(f"Scheduler error: {res.get('message')}", "error")

    except Exception as e:
        flash(f"Scheduler failed to run: {str(e)}", "error")

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/session/complete/<int:request_id>', methods=['POST'])
@admin_required
def complete_session_admin(request_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE allocations SET status = 'COMPLETED'
                WHERE request_id = %s AND status = 'ALLOCATED'
            """, (request_id,))

            cur.execute("""
                UPDATE requests SET status = 'COMPLETED'
                WHERE request_id = %s AND status = 'ALLOCATED'
            """, (request_id,))

        flash(f"🎉 Exam session for Request #{request_id} marked COMPLETED. The desk is now freed and available!", "success")
    except Exception as e:
        flash(f"Error completing session: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/slot/complete-all/<int:slot_id>', methods=['POST'])
@admin_required
def complete_entire_slot(slot_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE allocations SET status = 'COMPLETED'
                WHERE slot_id = %s AND status = 'ALLOCATED'
            """, (slot_id,))
            n = cur.rowcount

            cur.execute("""
                UPDATE requests SET status = 'COMPLETED'
                WHERE slot_id = %s AND status = 'ALLOCATED'
            """, (slot_id,))

        flash(f"🎉 Entire slot completed: {n} desk(s) freed and marked available!", "success")
    except Exception as e:
        flash(f"Error completing slot: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))

# PC Availability API (for interactive live filter)
@app.route('/api/pc-availability/<int:slot_id>')
def api_pc_availability(slot_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT l.lab_name, c.computer_id, c.computer_no, c.state,
                       CASE
                           WHEN c.state = 'MAINTENANCE' THEN 'MAINTENANCE'
                           WHEN EXISTS (
                               SELECT 1 FROM allocations ax
                               JOIN computers cx ON cx.computer_id=ax.computer_id
                               JOIN slots sx ON sx.slot_id=ax.slot_id
                               JOIN exams ex ON ex.exam_id=sx.exam_id
                               JOIN slots tx ON tx.slot_id=%s
                               JOIN exams et ON et.exam_id=tx.exam_id
                               WHERE cx.lab_id=c.lab_id AND ax.status='ALLOCATED'
                                 AND ex.exam_date=et.exam_date
                                 AND sx.start_time<tx.end_time AND tx.start_time<sx.end_time
                                 AND ex.exam_id<>et.exam_id
                           ) THEN 'RESERVED'
                           WHEN a.status = 'ALLOCATED' THEN 'OCCUPIED'
                           ELSE 'AVAILABLE'
                       END AS availability,
                       st.name AS student_name,
                       r.request_id
                FROM computers c
                JOIN labs l ON l.lab_id = c.lab_id
                LEFT JOIN allocations a ON a.allocation_id = (
                    SELECT a2.allocation_id FROM allocations a2
                    JOIN slots os ON os.slot_id=a2.slot_id
                    JOIN exams oe ON oe.exam_id=os.exam_id
                    JOIN slots ts ON ts.slot_id=%s
                    JOIN exams te ON te.exam_id=ts.exam_id
                    WHERE a2.computer_id=c.computer_id AND a2.status='ALLOCATED'
                      AND oe.exam_date=te.exam_date
                      AND os.start_time<ts.end_time AND ts.start_time<os.end_time
                    ORDER BY a2.allocation_id LIMIT 1
                )
                LEFT JOIN requests r ON r.request_id = a.request_id
                LEFT JOIN students st ON st.student_id = r.student_id
                ORDER BY l.lab_id ASC, c.computer_id ASC
            """, (slot_id, slot_id))
            results = cur.fetchall()
        return jsonify(results)
    finally:
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting LabSync Bright UI on http://127.0.0.1:{port}")
    app.run(host='127.0.0.1', port=port, debug=False)

