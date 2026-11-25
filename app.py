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
import urllib.request
import urllib.error
import re
import time
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


def process_automatic_expiries():
    """
    Automatic allocation lifecycle and expiry manager:
    1. Releases computers when an exam ends (exam_date + end_time <= CURRENT_TIMESTAMP):
       Transactionally transitions allocations & requests to 'COMPLETED',
       records release_reason = 'EXAM_COMPLETED' and released_at = NOW().
    2. Enforces check-in deadline for reservations (exam_date + start_time + deadline < CURRENT_TIMESTAMP):
       Confirmed no-shows transition to 'NO_SHOW',
       records release_reason = 'NO_SHOW_EXPIRY' and released_at = NOW().
    3. Triggers C++ scheduler if desks were freed by no-shows, so waiting queue gets placed.
    Returns: {'completed_count': int, 'noshow_count': int}
    """
    conn = get_db_connection()
    completed_count = 0
    noshow_count = 0
    try:
        with conn.cursor() as cur:
            # Step 1: Release computers when exam ends
            cur.execute("""
                SELECT a.allocation_id, a.request_id, a.slot_id, a.computer_id
                FROM allocations a
                JOIN slots s ON s.slot_id = a.slot_id
                JOIN exams e ON e.exam_id = s.exam_id
                WHERE a.status IN ('ALLOCATED', 'CHECKED_IN')
                  AND TIMESTAMP(e.exam_date, s.end_time) <= CURRENT_TIMESTAMP
                FOR UPDATE
            """)
            ended = cur.fetchall()
            if ended:
                req_ids = [r['request_id'] for r in ended]
                completed_count = len(req_ids)
                format_ids = ','.join(['%s'] * completed_count)
                cur.execute(f"""
                    UPDATE allocations
                    SET status = 'COMPLETED',
                        released_at = CURRENT_TIMESTAMP,
                        release_reason = 'EXAM_COMPLETED'
                    WHERE request_id IN ({format_ids})
                      AND status IN ('ALLOCATED', 'CHECKED_IN')
                """, req_ids)
                cur.execute(f"""
                    UPDATE requests
                    SET status = 'COMPLETED'
                    WHERE request_id IN ({format_ids})
                      AND status IN ('ALLOCATED', 'CHECKED_IN')
                """, req_ids)

            # Step 2: Release reservations for confirmed no-shows past check-in deadline
            deadline_mins = getattr(Config, 'CHECKIN_DEADLINE_MINUTES', 15)
            cur.execute("""
                SELECT a.allocation_id, a.request_id, a.slot_id, a.computer_id
                FROM allocations a
                JOIN slots s ON s.slot_id = a.slot_id
                JOIN exams e ON e.exam_id = s.exam_id
                WHERE a.status = 'ALLOCATED'
                  AND TIMESTAMP(e.exam_date, s.start_time) + INTERVAL %s MINUTE < CURRENT_TIMESTAMP
                FOR UPDATE
            """, (deadline_mins,))
            noshows = cur.fetchall()
            if noshows:
                req_ids = [r['request_id'] for r in noshows]
                noshow_count = len(req_ids)
                format_ids = ','.join(['%s'] * noshow_count)
                cur.execute(f"""
                    UPDATE allocations
                    SET status = 'NO_SHOW',
                        released_at = CURRENT_TIMESTAMP,
                        release_reason = 'NO_SHOW_EXPIRY'
                    WHERE request_id IN ({format_ids})
                      AND status = 'ALLOCATED'
                """, req_ids)
                cur.execute(f"""
                    UPDATE requests
                    SET status = 'NO_SHOW'
                    WHERE request_id IN ({format_ids})
                      AND status = 'ALLOCATED'
                """, req_ids)

        conn.commit()

        # If any no-shows freed desks, automatically invoke scheduler to allocate waiting requests
        if noshow_count > 0:
            try:
                run_cpp_scheduler()
            except Exception:
                pass

        return {'completed_count': completed_count, 'noshow_count': noshow_count}
    except Exception as e:
        conn.rollback()
        app.logger.warning("Automatic expiry processing error: %s", e)
        return {'completed_count': 0, 'noshow_count': 0, 'error': str(e)}
    finally:
        conn.close()


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

_last_expiry_sweep = 0

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

    # Periodic automatic allocation expiry sweep (throttled to at most once every 30 seconds)
    global _last_expiry_sweep
    now = time.time()
    if now - _last_expiry_sweep > 30 and getattr(app, '_db_initialized', False):
        _last_expiry_sweep = now
        try:
            process_automatic_expiries()
        except Exception:
            pass

# ==========================================
# ==========================================
# LABSYNC AI & CHATBOT HELPERS
# ==========================================

def _format_context_text(context, role='student'):
    """Format structured context into concise, crystal-clear facts for the LLM."""
    if context.get('db_error'):
        return "DATABASE STATUS: MySQL is currently disconnected or credentials need to be saved in Settings > Database."

    if role == 'admin':
        stats = context.get('system_stats', {})
        return (
            f"ADMIN SYSTEM METRICS & STATUS:\n"
            f"- Total Registered Students: {stats.get('students', 0)}\n"
            f"- Total Scheduled Exams: {stats.get('exams', 0)}\n"
            f"- Total Laboratories: {stats.get('labs', 0)}\n"
            f"- Computer Inventory: {stats.get('active_pcs', 0)} Active, {stats.get('maintenance_pcs', 0)} in Maintenance (Total: {stats.get('total_pcs', 0)})\n"
            f"- Pending Queue: {stats.get('pending_queue', 0)} requests awaiting desk allocation\n"
            f"- Active Desk Allocations: {stats.get('active_allocations', 0)}\n"
        )

    lines = []
    bookings = context.get('my_bookings', [])
    if bookings:
        lines.append("STUDENT'S REGISTERED EXAMS & COMPUTER DESK ALLOCATIONS:")
        for b in bookings[:10]:
            name = b.get('exam_name', 'Exam')
            code = b.get('subject_code', '')
            status = b.get('status', 'WAITING')
            date_str = str(b.get('exam_date', ''))
            time_str = f"{b.get('start_time')} - {b.get('end_time')}"
            
            if status in ('ALLOCATED', 'CHECKED_IN'):
                lab = b.get('lab_name') or 'Assigned Lab'
                desk = b.get('computer_no') or 'Desk assigned'
                station = f"Assigned Station: Desk {desk} in {lab}"
            elif status in ('WAITING', 'READY'):
                station = "Assigned Station: Pending allocation by C++ scheduler (will be assigned shortly)"
            elif status == 'COMPLETED':
                station = f"Exam Completed at Desk {b.get('computer_no', 'N/A')} in {b.get('lab_name', 'N/A')}"
            else:
                station = f"Status: {status}"

            lines.append(f"- Exam: {name} ({code}) | Status: {status} | {station} | Date: {date_str} | Time: {time_str}")
    else:
        lines.append("STUDENT'S REGISTERED EXAMS & COMPUTER DESK ALLOCATIONS: No bookings found. The student has not reserved any exams yet.")

    slots = context.get('upcoming_slots', [])
    if slots:
        lines.append("\nUPCOMING AVAILABLE EXAM SLOTS (OPEN FOR RESERVATION):")
        for s in slots[:12]:
            cap = int(s.get('capacity') or 0)
            alloc = int(s.get('allocated') or 0)
            avail = max(0, cap - alloc)
            lines.append(f"- Exam: {s.get('exam_name')} ({s.get('subject_code')}) | Date: {s.get('exam_date')} | Time: {s.get('start_time')} - {s.get('end_time')} | Available Seats: {avail} of {cap}")
    else:
        lines.append("\nUPCOMING AVAILABLE EXAM SLOTS: None currently scheduled.")

    return "\n".join(lines)


def _chatbot_context(user_id, role='student'):
    """Return schedule/booking data for student or system metrics for admin."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                if role == 'admin':
                    cur.execute("SELECT COUNT(*) AS total_students FROM students")
                    students = cur.fetchone()['total_students']
                    cur.execute("SELECT COUNT(*) AS total_exams FROM exams")
                    exams = cur.fetchone()['total_exams']
                    cur.execute("SELECT COUNT(*) AS total_labs FROM labs")
                    labs = cur.fetchone()['total_labs']
                    cur.execute("""SELECT COUNT(*) AS total_pcs,
                                          SUM(CASE WHEN state='ACTIVE' THEN 1 ELSE 0 END) AS active_pcs,
                                          SUM(CASE WHEN state='MAINTENANCE' THEN 1 ELSE 0 END) AS maint_pcs
                                   FROM computers""")
                    pcs = cur.fetchone() or {}
                    cur.execute("SELECT COUNT(*) AS pending FROM requests WHERE status IN ('READY', 'WAITING')")
                    pending = cur.fetchone()['pending']
                    cur.execute("SELECT COUNT(*) AS allocated FROM allocations WHERE status IN ('ALLOCATED', 'CHECKED_IN')")
                    allocated = cur.fetchone()['allocated']
                    return {
                        "role": "admin",
                        "system_stats": {
                            "students": students, "exams": exams, "labs": labs,
                            "total_pcs": pcs.get('total_pcs') or 0,
                            "active_pcs": pcs.get('active_pcs') or 0,
                            "maintenance_pcs": pcs.get('maint_pcs') or 0,
                            "pending_queue": pending,
                            "active_allocations": allocated
                        }
                    }
                else:
                    cur.execute("""SELECT e.exam_name, e.subject_code, e.exam_date, s.start_time, s.end_time, s.capacity,
                                       (SELECT COUNT(*) FROM allocations a WHERE a.slot_id=s.slot_id AND a.status IN ('ALLOCATED', 'CHECKED_IN')) allocated
                                FROM exams e JOIN slots s ON s.exam_id=e.exam_id
                                ORDER BY e.exam_date ASC, s.start_time ASC LIMIT 100""")
                    exams = cur.fetchall()
                    cur.execute("""SELECT e.exam_name, e.subject_code, e.exam_date, s.start_time, s.end_time, r.status,
                                       l.lab_name, c.computer_no, r.request_id, r.priority
                                FROM requests r 
                                JOIN exams e ON e.exam_id=r.exam_id 
                                JOIN slots s ON s.slot_id=r.slot_id
                                LEFT JOIN allocations a ON a.request_id=r.request_id AND a.status IN ('ALLOCATED', 'CHECKED_IN')
                                LEFT JOIN computers c ON c.computer_id=a.computer_id 
                                LEFT JOIN labs l ON l.lab_id=c.lab_id
                                WHERE r.student_id=%s ORDER BY r.request_time DESC LIMIT 50""", (user_id,))
                    bookings = cur.fetchall()
                    return {"role": "student", "upcoming_slots": exams, "my_bookings": bookings}
        finally:
            conn.close()
    except Exception as exc:
        app.logger.warning("Database unavailable for chatbot context: %s", exc)
        return {"role": role, "db_error": True, "upcoming_slots": [], "my_bookings": []}


def _local_chat_answer(question, context, role='student'):
    """Intelligent, deterministic local assistant when Ollama is offline or processing."""
    q = question.lower().strip()

    # 1. Greetings & Pleasantries
    if any(re.search(rf"\b{word}\b", q) for word in ['hi', 'hello', 'hey', 'greetings', 'morning', 'afternoon', 'evening', 'help', 'who are you', 'what can you do']):
        if role == 'admin':
            return (
                "Hello Administrator! 👋 I'm **LabSync AI**. I can assist you with real-time **hardware status**, "
                "**active allocations**, **pending queue counts**, and details about the **C++ scheduling engine**. How can I help?"
            )
        return (
            "Hello there! 😊 I'm **LabSync AI**, your campus assistant. I can help you check your **exam schedule**, "
            "find your **assigned computer desk & lab location**, view **available seats**, and answer questions about **scheduling rules** or **check-in deadlines**. How can I assist you today?"
        )

    # 2. Thank you & Politeness
    if any(re.search(rf"\b{word}\b", q) for word in ['thank', 'thanks', 'thx', 'bye', 'goodbye', 'awesome', 'great']):
        return "You're very welcome! Best of luck with your exams, and feel free to ask anytime if you need help. Have a wonderful day! 🌟"

    # Admin portal queries
    if role == 'admin':
        stats = context.get('system_stats', {})
        if any(k in q for k in ('pc', 'computer', 'hardware', 'device')):
            return f"LabSync currently tracks **{stats.get('total_pcs', 0)} total computers** (**{stats.get('active_pcs', 0)} active**, **{stats.get('maintenance_pcs', 0)} in maintenance**)."
        if any(k in q for k in ('pending', 'queue', 'waiting', 'unallocated')):
            return f"There are currently **{stats.get('pending_queue', 0)} requests** waiting in queue for desk allocation."
        if any(k in q for k in ('student', 'user', 'registration')):
            return f"There are **{stats.get('students', 0)} registered students** currently in the system."
        if any(k in q for k in ('exam', 'labs', 'overview', 'stats', 'status', 'summary', 'system')):
            return (f"📊 **System Status**: **{stats.get('students', 0)} Students**, **{stats.get('exams', 0)} Exams**, "
                    f"**{stats.get('labs', 0)} Labs**, **{stats.get('active_allocations', 0)} Active Desks**, and **{stats.get('pending_queue', 0)} Pending**.")
        if any(k in q for k in ('priority', 'fcfs', 'scheduler', 'algorithm', 'engine', 'bridge')):
            return ("The C++ scheduling engine orders requests by **Priority** (1=High, 2=Normal, 3=Low), followed by **FCFS** (request arrival time). "
                    "Allocations run via the C++ bridge with transactional deadlock detection and automatic retries.")
        return "I can report real-time system metrics (computers, pending queue, active allocations) or explain the scheduling engine. What would you like to know?"

    # Student portal queries
    bookings = context.get('my_bookings', [])
    upcoming = context.get('upcoming_slots', [])

    # 3. Cancellation Instructions
    if any(k in q for k in ('cancel', 'cancellation', 'drop booking', 'how to cancel', 'can i cancel')):
        return "To cancel an exam reservation, click the **Cancel Booking** button on your reservation card on the Student Dashboard. Your allocated desk will immediately be freed up for other students."

    # 4. Check-in & Deadline Rules
    if any(k in q for k in ('check in', 'checkin', 'deadline', 'no show', 'how to check in', 'when can i check in')):
        return (
            "Check-in opens **30 minutes before** your scheduled exam start time and closes **15 minutes after** start time. "
            "Once within the window, click the **Check In** button on your dashboard to confirm your arrival at your assigned desk. "
            "Missing the check-in deadline releases the desk as a no-show so waiting students can be seated."
        )

    # 5. Priority, FCFS & Scheduling Algorithm
    if any(k in q for k in ('priority', 'fcfs', 'scheduler', 'scheduling', 'algorithm', 'how it works', 'how does it work')):
        return (
            "LabSync uses an automated **Priority + FCFS (First-Come, First-Served)** scheduler. "
            "Requests with higher numerical priority (1 = High, 2 = Normal, 3 = Low) are processed first. "
            "When students share the same priority, desks are allocated strictly in the order requests were submitted. "
            "Our C++ scheduling engine guarantees fair allocation and prevents database deadlocks."
        )

    # 6. Available Exam Slots / Open Seats Queries
    if any(k in q for k in ('available', 'free seat', 'open seat', 'what can i book', 'upcoming slot', 'available slot', 'exam slot', 'what slots', 'what exam slots')):
        if not upcoming:
            return "There are currently no upcoming exam slots listed in LabSync."
        rows = []
        for e in upcoming[:5]:
            cap = int(e.get('capacity') or 0)
            alloc = int(e.get('allocated') or 0)
            avail = max(0, cap - alloc)
            rows.append(f"• **{e.get('exam_name')}** ({e.get('subject_code')}): **{e.get('exam_date')}** ({e.get('start_time')}-{e.get('end_time')}) — **{avail} seats free**")
        return "Here are the upcoming exam slots available for booking:\n" + "\n".join(rows)

    # 7. Specific Exam / Subject Search (with CS Acronym Expansion)
    acronym_aliases = {
        'dbms': ['database', 'management'],
        'dsa': ['data structure', 'algorithm'],
        'os': ['operating system'],
        'cn': ['computer network', 'network'],
        'oop': ['object oriented'],
        'oops': ['object oriented'],
        'ai': ['artificial intelligence'],
        'ml': ['machine learning'],
    }

    def _matches_subject(item, text):
        name = item.get('exam_name', '').lower()
        code = item.get('subject_code', '').lower()
        if code and code in text:
            return True
        for acr, words in acronym_aliases.items():
            if re.search(rf"\b{acr}\b", text):
                if any(w in name for w in words):
                    return True
        keywords = [w for w in re.split(r'[\s&/,.-]+', name) if len(w) > 3]
        return any(w in text for w in keywords)

    matched_my_booking = next((b for b in bookings if _matches_subject(b, q)), None)
    matched_upcoming = next((u for u in upcoming if _matches_subject(u, q)), None)

    if matched_my_booking:
        b = matched_my_booking
        status = b.get('status', 'WAITING')
        exam_name = b.get('exam_name', 'Exam')
        code = b.get('subject_code', '')
        date = b.get('exam_date', '')
        start = b.get('start_time', '')
        end = b.get('end_time', '')
        if status in ('ALLOCATED', 'CHECKED_IN'):
            desk = b.get('computer_no', 'Assigned Desk')
            lab = b.get('lab_name', 'Main Lab')
            action = "You are checked in and seated at" if status == 'CHECKED_IN' else "Your allocated station is"
            return (
                f"For **{exam_name}** ({code}), {action} **Desk {desk}** in **{lab}**. "
                f"Your session is on **{date}** from **{start} to {end}**! 🎯"
            )
        elif status in ('WAITING', 'READY'):
            return (
                f"Your booking for **{exam_name}** ({code}) on **{date}** ({start} - {end}) is confirmed in the queue (**{status}**). "
                f"The scheduler is actively assigning desks—your specific computer number will appear as soon as allocation runs! ⏳"
            )
        elif status == 'COMPLETED':
            return f"Your exam for **{exam_name}** ({code}) on **{date}** has already been **COMPLETED**. 🎉"
        else:
            return f"Your booking for **{exam_name}** ({code}) currently has status **{status}**."

    if matched_upcoming:
        cap = int(matched_upcoming.get('capacity') or 0)
        alloc = int(matched_upcoming.get('allocated') or 0)
        avail = max(0, cap - alloc)
        return (
            f"Yes! **{matched_upcoming.get('exam_name')}** ({matched_upcoming.get('subject_code')}) is scheduled for "
            f"**{matched_upcoming.get('exam_date')}** from **{matched_upcoming.get('start_time')} - {matched_upcoming.get('end_time')}** "
            f"with **{avail} seats available** (Capacity: {cap}). You can reserve your seat directly on the dashboard!"
        )

    # 8. Location / Desk / PC / Room Queries
    is_location_or_desk = any(k in q for k in (
        'where', 'desk', 'pc', 'computer', 'room', 'lab', 'seat', 'station', 'location', 
        'where am i', 'which room', 'which lab', 'which pc', 'what pc', 'what computer', 'what desk'
    ))

    # 9. Booking / Registration Verification
    is_booking_check = any(k in q for k in (
        'did i book', 'do i have', 'my booking', 'my status', 'booking status', 'my exam', 'my test', 
        'my schedule', 'am i registered', 'my reservation', 'what exams do i have', 'all booking', 'all my bookings'
    ))

    if is_location_or_desk or is_booking_check:
        if not bookings:
            return "You don't have any exams booked yet! You can explore and book any available exam from the **Available Exam Slots** section on your dashboard. 🚀"
        
        items = []
        for b in bookings[:5]:
            status = b.get('status', 'WAITING')
            exam_name = b.get('exam_name', 'Exam')
            code = b.get('subject_code', '')
            date = b.get('exam_date', '')
            start = b.get('start_time', '')
            end = b.get('end_time', '')

            if status in ('ALLOCATED', 'CHECKED_IN'):
                desk = b.get('computer_no', 'Desk assigned')
                lab = b.get('lab_name', 'Lab')
                tag = "Checked In" if status == 'CHECKED_IN' else "Allocated"
                items.append(f"• **{exam_name}** ({code}): **Desk {desk}** in **{lab}** | **{date}** ({start} - {end}) [**{tag}**]")
            elif status in ('WAITING', 'READY'):
                items.append(f"• **{exam_name}** ({code}): Desk **Pending allocation** | **{date}** ({start} - {end}) [**{status}**]")
            elif status == 'COMPLETED':
                items.append(f"• **{exam_name}** ({code}): **Completed** on {date}")
            else:
                items.append(f"• **{exam_name}** ({code}): Status **{status}** on {date}")

        if is_location_or_desk:
            prefix = "Here is your desk allocation and exam location details:\n"
        else:
            prefix = "Here are your registered exam reservations:\n"
        return prefix + "\n".join(items)

    # Default friendly guidance
    return (
        "I'm here to help with your **exam schedules**, **computer desk allocations**, **lab locations**, and **system rules**! "
        "Feel free to ask me questions like *'Where is my exam?'*, *'What PC did I get?'*, *'Do I have any bookings?'*, or *'What slots are available?'*."
    )


def _call_chat_ai(question, context, role='student'):
    """Send request to Ollama and guarantee a clean, concise, direct answer with fabulous tone."""
    url = "http://127.0.0.1:11434/api/chat"
    context_str = _format_context_text(context, role=role)

    system_prompt = f"""You are LabSync AI, the friendly, helpful, and intelligent campus assistant for the LabSync computer lab and exam scheduling system.

TONE & STYLE:
- Speak in a warm, encouraging, polite, and natural tone (fabulous customer experience!).
- Keep your answers concise, direct, and completely informative (1 to 3 clear sentences, or a compact bulleted list).
- ALWAYS bold important entities: **Exam Name**, **Subject Code**, **Lab Name**, **Desk Number / PC Number**, **Date**, **Time Slot**, **Status**.

CORE RULES:
1. In LabSync, the 'STUDENT'S REGISTERED EXAMS & COMPUTER DESK ALLOCATIONS' section in Database Context lists the student's booked exams and assigned desks.
2. If asked where their exam is, what desk/pc they got, or what room to go to, look at their bookings:
   - If ALLOCATED or CHECKED_IN: state the exam, the lab room, the computer number (e.g. **PC-005** in **Lab 1**), date, and time.
   - If WAITING or READY: warmly explain that their exam booking is confirmed and in the queue; the scheduler is allocating seats and their desk will appear shortly.
   - If COMPLETED: mention that their exam session has finished.
3. If the student has NO bookings, kindly inform them they don't have any exams booked yet and suggest choosing a slot from the dashboard.
4. If asked about exam schedules, available seats, priority/FCFS rules, or how to check in, answer accurately from the context and system rules.
5. NEVER output <think> tags or internal monologues.
"""

    payload = {
        "model": "labsync-ai:latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Database Context:\n{context_str}\n\nStudent/User Question: {question}\n\nAnswer:"
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.25
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=50) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw_reply = data.get("message", {}).get("content", "").strip()

        # If content is empty but thinking has content, extract from thinking
        if not raw_reply and data.get("message", {}).get("thinking"):
            thinking_text = data.get("message", {}).get("thinking", "").strip()
            lines = [l.strip() for l in thinking_text.splitlines() if l.strip()]
            for l in reversed(lines):
                if len(l) > 20 and not l.startswith('*') and not l.lower().startswith('okay'):
                    raw_reply = l
                    break

        if "</think>" in raw_reply:
            raw_reply = raw_reply.split("</think>")[-1].strip()

        raw_reply = re.sub(r"<think>.*?</think>", "", raw_reply, flags=re.DOTALL)
        raw_reply = re.sub(r"^<think>.*", "", raw_reply, flags=re.DOTALL)
        raw_reply = re.sub(r"^(Okay|Sure|Alright)[,\s]+(the user|I need to|let me).*?(\n\n|\.\s+)", "", raw_reply, flags=re.DOTALL | re.IGNORECASE)

        clean = raw_reply.strip()
        return clean if clean else None

    except urllib.error.URLError as err:
        app.logger.warning("Ollama connection error: %s", err)
        return None
    except Exception as err:
        app.logger.warning("AI response processing error: %s", err)
        return None


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
    try:
        process_automatic_expiries()
    except Exception:
        pass

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
                       (SELECT COUNT(*) FROM allocations a WHERE a.slot_id = s.slot_id AND a.status IN ('ALLOCATED', 'CHECKED_IN')) AS allocated_count
                FROM exams e
                JOIN slots s ON s.exam_id = e.exam_id
                ORDER BY e.exam_date ASC, s.start_time ASC
            """)
            slots_data = cur.fetchall()

            # 3. Fetch student's bookings (with lifecycle timestamps, check-in status and deadlines)
            cur.execute("""
                SELECT r.request_id, r.priority, r.request_time, r.status,
                       e.exam_name, e.subject_code, e.exam_date,
                       s.start_time, s.end_time,
                       l.lab_name, c.computer_no,
                       a.checked_in_at, a.released_at, a.release_reason,
                       CASE
                           WHEN r.status = 'ALLOCATED'
                                AND CURRENT_TIMESTAMP >= TIMESTAMP(e.exam_date, s.start_time) - INTERVAL 30 MINUTE
                                AND CURRENT_TIMESTAMP <= TIMESTAMP(e.exam_date, s.start_time) + INTERVAL 15 MINUTE
                           THEN 1 ELSE 0
                       END AS can_check_in,
                       TIMESTAMPDIFF(MINUTE, CURRENT_TIMESTAMP, TIMESTAMP(e.exam_date, s.start_time)) AS mins_until_start,
                       TIMESTAMPDIFF(MINUTE, TIMESTAMP(e.exam_date, s.start_time), CURRENT_TIMESTAMP) AS mins_since_start
                FROM requests r
                JOIN exams e ON e.exam_id = r.exam_id
                JOIN slots s ON s.slot_id = r.slot_id
                LEFT JOIN allocations a ON a.request_id = r.request_id
                LEFT JOIN computers c ON c.computer_id = a.computer_id
                LEFT JOIN labs l ON l.lab_id = c.lab_id
                WHERE r.student_id = %s
                ORDER BY r.request_time DESC
            """, (sid,))
            my_bookings = cur.fetchall()

            active_bookings = [b for b in my_bookings if b['status'] in ('READY', 'WAITING', 'ALLOCATED', 'CHECKED_IN')]
            past_bookings = [b for b in my_bookings if b['status'] in ('COMPLETED', 'NO_SHOW', 'CANCELLED', 'EXPIRED')]

        return render_template(
            'student_dashboard.html',
            student=student,
            slots=slots_data,
            bookings=active_bookings,
            past_bookings=past_bookings,
            checkin_deadline_mins=getattr(Config, 'CHECKIN_DEADLINE_MINUTES', 15)
        )
    finally:
        conn.close()


@app.route('/student/check-in/<int:request_id>', methods=['POST'])
@student_required
def check_in_student(request_id):
    sid = session['user_id']
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.request_id, r.status, e.exam_name, e.exam_date, s.start_time, s.end_time,
                       c.computer_no, l.lab_name,
                       TIMESTAMPDIFF(MINUTE, CURRENT_TIMESTAMP, TIMESTAMP(e.exam_date, s.start_time)) AS mins_until_start,
                       TIMESTAMPDIFF(MINUTE, TIMESTAMP(e.exam_date, s.start_time), CURRENT_TIMESTAMP) AS mins_since_start
                FROM requests r
                JOIN exams e ON e.exam_id = r.exam_id
                JOIN slots s ON s.slot_id = r.slot_id
                JOIN allocations a ON a.request_id = r.request_id
                JOIN computers c ON c.computer_id = a.computer_id
                JOIN labs l ON l.lab_id = c.lab_id
                WHERE r.request_id = %s AND r.student_id = %s
                FOR UPDATE
            """, (request_id, sid))
            req = cur.fetchone()

            if not req:
                flash("Allocation not found or unauthorized.", "error")
                return redirect(url_for('student_dashboard'))

            if req['status'] == 'CHECKED_IN':
                flash("You have already checked in for this desk!", "info")
                return redirect(url_for('student_dashboard'))

            if req['status'] != 'ALLOCATED':
                flash(f"Cannot check in: Booking status is {req['status']}.", "warning")
                return redirect(url_for('student_dashboard'))

            deadline = getattr(Config, 'CHECKIN_DEADLINE_MINUTES', 15)
            window_before = getattr(Config, 'CHECKIN_WINDOW_BEFORE_MINUTES', 30)

            if req['mins_until_start'] > window_before:
                flash(f"Check-in opens {window_before} minutes before your exam starts.", "warning")
                return redirect(url_for('student_dashboard'))

            if req['mins_since_start'] > deadline:
                flash(f"Check-in deadline has expired ({deadline} minutes after start time). Reservation marked as no-show.", "error")
                return redirect(url_for('student_dashboard'))

            cur.execute("""
                UPDATE allocations
                SET status = 'CHECKED_IN', checked_in_at = CURRENT_TIMESTAMP
                WHERE request_id = %s AND status = 'ALLOCATED'
            """, (request_id,))

            cur.execute("""
                UPDATE requests
                SET status = 'CHECKED_IN'
                WHERE request_id = %s AND status = 'ALLOCATED'
            """, (request_id,))

        conn.commit()
        flash(f"🎉 Check-in confirmed! You are seated at Desk {req['computer_no']} ({req['lab_name']}). Good luck!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Check-in failed: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('student_dashboard'))


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
    freed_slot = False
    try:
        with conn.cursor() as cur:
            # Check ownership and cancellable status
            cur.execute("""
                SELECT request_id, status FROM requests
                WHERE request_id = %s AND student_id = %s
                AND status IN ('READY', 'WAITING', 'ALLOCATED', 'CHECKED_IN')
                FOR UPDATE
            """, (request_id, sid))
            req = cur.fetchone()

            if not req:
                flash("Booking could not be cancelled or was already completed.", "error")
                return redirect(url_for('student_dashboard'))

            if req['status'] in ('ALLOCATED', 'CHECKED_IN'):
                freed_slot = True

            # Cancel allocation if exists
            cur.execute("""
                UPDATE allocations 
                SET status = 'CANCELLED', released_at = CURRENT_TIMESTAMP, release_reason = 'STUDENT_CANCELLED'
                WHERE request_id = %s AND status IN ('ALLOCATED', 'CHECKED_IN')
            """, (request_id,))

            # Cancel request
            cur.execute("""
                UPDATE requests SET status = 'CANCELLED'
                WHERE request_id = %s
            """, (request_id,))

        conn.commit()

        if freed_slot:
            try:
                run_cpp_scheduler()
            except Exception:
                pass

        flash("Booking cancelled successfully. Your desk has been released.", "info")
    except Exception as e:
        conn.rollback()
        flash(f"Cancellation failed: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('student_dashboard'))

@app.route('/api/chat', methods=['POST'])
def chat_api():
    role = session.get('role', 'student')
    user_id = session.get('user_id', 0)
    body = request.get_json(silent=True) or {}
    question = str(body.get('message', '')).strip()

    if not question:
        return jsonify({"reply": "Please enter a question."}), 400
    if len(question) > 1000:
        return jsonify({"reply": "Please keep your question under 1000 characters."}), 400

    try:
        context = _chatbot_context(user_id, role=role)
        mode = "ai"
        reply = _call_chat_ai(question, context, role=role)
        if not reply:
            reply = _local_chat_answer(question, context, role=role)
            mode = "local"
        return jsonify({"reply": reply, "mode": mode, "status": "ok"})
    except Exception as exc:
        app.logger.exception("Chatbot request failed: %s", exc)
        return jsonify({"reply": "I couldn't access LabSync data right now. Please verify database connection."}), 503


@app.route('/api/ai-status')
def ai_status():
    """Report Ollama connectivity and model readiness."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get('name', '') for m in data.get('models', [])]
            has_model = any('labsync-ai' in m or 'qwen' in m for m in models)
            active_model = next((m for m in models if 'labsync-ai' in m), models[0] if models else "none")
            return jsonify({
                "connected": True,
                "model": active_model,
                "has_labsync": has_model
            })
    except Exception:
        return jsonify({"connected": False, "model": None, "has_labsync": False})

# ==========================================
# ADMIN PORTAL ROUTES
# ==========================================

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    try:
        process_automatic_expiries()
    except Exception:
        pass

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

            cur.execute("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN state = 'ACTIVE' THEN 1 ELSE 0 END) AS active_pcs,
                       SUM(CASE WHEN state = 'MAINTENANCE' THEN 1 ELSE 0 END) AS maintenance_pcs
                FROM computers
            """)
            pc_counts = cur.fetchone() or {}
            total_pcs = pc_counts.get('total') or 0
            active_pcs = pc_counts.get('active_pcs') or 0
            maintenance_pcs = pc_counts.get('maintenance_pcs') or 0

            cur.execute("SELECT COUNT(*) AS total FROM requests WHERE status IN ('READY', 'WAITING')")
            pending_requests = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM allocations WHERE status IN ('ALLOCATED', 'CHECKED_IN')")
            active_allocations = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM allocations WHERE status = 'CHECKED_IN'")
            checked_in_count = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM requests WHERE status = 'COMPLETED'")
            completed_count = cur.fetchone()['total']

            cur.execute("SELECT COUNT(*) AS total FROM requests WHERE status = 'NO_SHOW'")
            noshow_count = cur.fetchone()['total']

            # Exams list
            cur.execute("SELECT * FROM exams ORDER BY exam_date DESC")
            exams = cur.fetchall()

            # Slots list
            cur.execute("""
                SELECT s.slot_id, s.exam_id, s.start_time, s.end_time, s.capacity,
                       e.exam_name, e.subject_code, e.exam_date,
                       (SELECT COUNT(*) FROM allocations a WHERE a.slot_id = s.slot_id AND a.status IN ('ALLOCATED', 'CHECKED_IN')) AS current_allocated
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

            # All bookings & requests (including lifecycle states and timestamps)
            cur.execute("""
                SELECT r.request_id, r.priority, r.request_time, r.status,
                       st.student_id, st.name AS student_name, st.email AS student_email,
                       e.exam_name, e.subject_code, e.exam_date,
                       s.slot_id, s.start_time, s.end_time,
                       l.lab_name, c.computer_no, c.computer_id,
                       a.checked_in_at, a.released_at, a.release_reason
                FROM requests r
                JOIN students st ON st.student_id = r.student_id
                JOIN exams e ON e.exam_id = r.exam_id
                JOIN slots s ON s.slot_id = r.slot_id
                LEFT JOIN allocations a ON a.request_id = r.request_id
                LEFT JOIN computers c ON c.computer_id = a.computer_id
                LEFT JOIN labs l ON l.lab_id = c.lab_id
                ORDER BY r.request_time DESC
            """)
            all_bookings = cur.fetchall()

            # Comprehensive PC inventory with current allocation & maintenance state
            cur.execute("""
                SELECT c.computer_id, c.computer_no, c.state, l.lab_id, l.lab_name,
                       a.status AS allocation_status,
                       st.name AS student_name,
                       r.request_id,
                       e.exam_name,
                       s.start_time, s.end_time
                FROM computers c
                JOIN labs l ON l.lab_id = c.lab_id
                LEFT JOIN allocations a ON a.allocation_id = (
                    SELECT a2.allocation_id FROM allocations a2
                    JOIN slots os ON os.slot_id = a2.slot_id
                    JOIN exams oe ON oe.exam_id = os.exam_id
                    WHERE a2.computer_id = c.computer_id 
                      AND a2.status IN ('ALLOCATED', 'CHECKED_IN')
                      AND oe.exam_date = CURRENT_DATE
                    ORDER BY a2.allocation_id DESC LIMIT 1
                )
                LEFT JOIN requests r ON r.request_id = a.request_id
                LEFT JOIN students st ON st.student_id = r.student_id
                LEFT JOIN slots s ON s.slot_id = a.slot_id
                LEFT JOIN exams e ON e.exam_id = s.exam_id
                ORDER BY l.lab_id ASC, c.computer_id ASC
            """)
            all_computers = cur.fetchall()

            # Registered Students Directory with metrics
            cur.execute("""
                SELECT s.student_id, s.name, s.email,
                       COUNT(r.request_id) AS total_bookings,
                       SUM(CASE WHEN r.status IN ('ALLOCATED', 'CHECKED_IN') THEN 1 ELSE 0 END) AS active_allocations,
                       SUM(CASE WHEN r.status = 'COMPLETED' THEN 1 ELSE 0 END) AS completed_exams,
                       SUM(CASE WHEN r.status = 'NO_SHOW' THEN 1 ELSE 0 END) AS no_shows
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
            "active_pcs": active_pcs,
            "maintenance_pcs": maintenance_pcs,
            "pending": pending_requests,
            "allocated": active_allocations,
            "checked_in": checked_in_count,
            "completed": completed_count,
            "no_shows": noshow_count
        }

        return render_template(
            'admin_dashboard.html',
            stats=stats,
            exams=exams,
            slots=slots,
            labs=labs,
            bookings=all_bookings,
            computers=all_computers,
            students=registered_students,
            checkin_deadline_mins=getattr(Config, 'CHECKIN_DEADLINE_MINUTES', 15)
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
            cur.execute("SELECT computer_id, computer_no, state, lab_id FROM computers WHERE computer_id = %s FOR UPDATE", (computer_id,))
            pc = cur.fetchone()
            if not pc:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                    return jsonify({"success": False, "message": "Computer not found"}), 404
                flash("Computer not found.", "error")
                return redirect(url_for('admin_dashboard'))

            new_state = 'MAINTENANCE' if pc['state'] == 'ACTIVE' else 'ACTIVE'
            cur.execute("UPDATE computers SET state = %s WHERE computer_id = %s", (new_state, computer_id))

            reallocated_msg = ""
            affected = []
            if new_state == 'MAINTENANCE':
                # Re-queue any active/checked-in allocations on this computer so students aren't stranded on broken hardware
                cur.execute("""
                    SELECT a.allocation_id, a.request_id, r.student_id, r.exam_id, r.slot_id
                    FROM allocations a
                    JOIN requests r ON r.request_id = a.request_id
                    WHERE a.computer_id = %s AND a.status IN ('ALLOCATED', 'CHECKED_IN')
                    FOR UPDATE
                """, (computer_id,))
                affected = cur.fetchall()
                if affected:
                    for aff in affected:
                        cur.execute("""
                            UPDATE allocations 
                            SET status = 'CANCELLED', released_at = CURRENT_TIMESTAMP, release_reason = 'PC_MAINTENANCE' 
                            WHERE allocation_id = %s
                        """, (aff['allocation_id'],))
                        cur.execute("""
                            UPDATE requests 
                            SET status = 'WAITING' 
                            WHERE request_id = %s
                        """, (aff['request_id'],))
                    reallocated_msg = f" (Notice: {len(affected)} active reservation(s) re-queued for desk reassignment)."

        conn.commit()

        if new_state == 'MAINTENANCE' and affected:
            try:
                run_cpp_scheduler()
            except Exception:
                pass

        msg = f"🖥️ {pc['computer_no']} state set to {new_state}{reallocated_msg}"
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({
                "success": True,
                "computer_id": computer_id,
                "computer_no": pc['computer_no'],
                "state": new_state,
                "message": msg
            })

        flash(msg, "warning" if new_state == 'MAINTENANCE' else "success")
    except Exception as e:
        conn.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({"success": False, "message": str(e)}), 500
        flash(f"Error updating PC state: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/booking/check-in/<int:request_id>', methods=['POST'])
@admin_required
def admin_check_in(request_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE allocations
                SET status = 'CHECKED_IN', checked_in_at = CURRENT_TIMESTAMP
                WHERE request_id = %s AND status = 'ALLOCATED'
            """, (request_id,))
            cur.execute("""
                UPDATE requests
                SET status = 'CHECKED_IN'
                WHERE request_id = %s AND status = 'ALLOCATED'
            """, (request_id,))
        conn.commit()
        flash(f"✅ Student for Request #{request_id} marked as CHECKED IN.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error checking in student: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/booking/no-show/<int:request_id>', methods=['POST'])
@admin_required
def admin_mark_no_show(request_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE allocations
                SET status = 'NO_SHOW', released_at = CURRENT_TIMESTAMP, release_reason = 'ADMIN_MANUAL_NO_SHOW'
                WHERE request_id = %s AND status IN ('ALLOCATED', 'READY', 'WAITING')
            """, (request_id,))
            cur.execute("""
                UPDATE requests
                SET status = 'NO_SHOW'
                WHERE request_id = %s AND status IN ('ALLOCATED', 'READY', 'WAITING')
            """, (request_id,))
        conn.commit()
        try:
            run_cpp_scheduler()
        except Exception:
            pass
        flash(f"⚠️ Request #{request_id} marked as NO-SHOW. Desk released and reallocated if waiting students exist.", "warning")
    except Exception as e:
        conn.rollback()
        flash(f"Error marking no-show: {str(e)}", "error")
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/scheduler/expire-check', methods=['POST'])
@admin_required
def admin_trigger_expiry():
    res = process_automatic_expiries()
    if res.get('error'):
        flash(f"Expiry check encountered an error: {res['error']}", "error")
    else:
        c = res.get('completed_count', 0)
        n = res.get('noshow_count', 0)
        flash(f"⚡ Expiry sweep completed: {c} ended exam(s) released & marked COMPLETED, {n} no-show reservation(s) released.", "success")
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
                UPDATE allocations 
                SET status = 'COMPLETED', released_at = CURRENT_TIMESTAMP, release_reason = 'MANUAL_COMPLETE'
                WHERE request_id = %s AND status IN ('ALLOCATED', 'CHECKED_IN')
            """, (request_id,))

            cur.execute("""
                UPDATE requests 
                SET status = 'COMPLETED'
                WHERE request_id = %s AND status IN ('ALLOCATED', 'CHECKED_IN')
            """, (request_id,))
        conn.commit()
        try:
            run_cpp_scheduler()
        except Exception:
            pass
        flash(f"🎉 Exam session for Request #{request_id} marked COMPLETED. The desk is now freed and available!", "success")
    except Exception as e:
        conn.rollback()
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
                UPDATE allocations 
                SET status = 'COMPLETED', released_at = CURRENT_TIMESTAMP, release_reason = 'SLOT_COMPLETED'
                WHERE slot_id = %s AND status IN ('ALLOCATED', 'CHECKED_IN')
            """, (slot_id,))
            n = cur.rowcount

            cur.execute("""
                UPDATE requests 
                SET status = 'COMPLETED'
                WHERE slot_id = %s AND status IN ('ALLOCATED', 'CHECKED_IN')
            """, (slot_id,))
        conn.commit()
        try:
            run_cpp_scheduler()
        except Exception:
            pass
        flash(f"🎉 Entire slot completed: {n} desk(s) freed and marked available!", "success")
    except Exception as e:
        conn.rollback()
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
                               JOIN computers cx ON cx.computer_id = ax.computer_id
                               JOIN slots sx ON sx.slot_id = ax.slot_id
                               JOIN exams ex ON ex.exam_id = sx.exam_id
                               JOIN slots tx ON tx.slot_id = %s
                               JOIN exams et ON et.exam_id = tx.exam_id
                               WHERE cx.lab_id = c.lab_id AND ax.status IN ('ALLOCATED', 'CHECKED_IN')
                                 AND ex.exam_date = et.exam_date
                                 AND sx.start_time < tx.end_time AND tx.start_time < sx.end_time
                                 AND ex.exam_id <> et.exam_id
                           ) THEN 'RESERVED'
                           WHEN a.status IN ('ALLOCATED', 'CHECKED_IN') THEN 'OCCUPIED'
                           ELSE 'AVAILABLE'
                       END AS availability,
                       st.name AS student_name,
                       r.request_id,
                       a.status AS allocation_status,
                       a.checked_in_at
                FROM computers c
                JOIN labs l ON l.lab_id = c.lab_id
                LEFT JOIN allocations a ON a.allocation_id = (
                    SELECT a2.allocation_id FROM allocations a2
                    JOIN slots os ON os.slot_id = a2.slot_id
                    JOIN exams oe ON oe.exam_id = os.exam_id
                    JOIN slots ts ON ts.slot_id = %s
                    JOIN exams te ON te.exam_id = ts.exam_id
                    WHERE a2.computer_id = c.computer_id AND a2.status IN ('ALLOCATED', 'CHECKED_IN')
                      AND oe.exam_date = te.exam_date
                      AND os.start_time < ts.end_time AND ts.start_time < os.end_time
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

