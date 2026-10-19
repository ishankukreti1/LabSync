import pymysql
import pymysql.cursors
from config import Config
from werkzeug.security import generate_password_hash

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS students(
        student_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(120) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS admins(
        admin_id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        email VARCHAR(120) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS exams(
        exam_id INT AUTO_INCREMENT PRIMARY KEY,
        exam_name VARCHAR(120) NOT NULL,
        subject_code VARCHAR(30) NOT NULL,
        exam_date DATE NOT NULL,
        priority TINYINT NOT NULL DEFAULT 2,
        CONSTRAINT chk_exam_priority CHECK(priority BETWEEN 1 AND 3)
    )""",
    """CREATE TABLE IF NOT EXISTS slots(
        slot_id INT AUTO_INCREMENT PRIMARY KEY,
        exam_id INT NOT NULL,
        start_time TIME NOT NULL,
        end_time TIME NOT NULL,
        capacity INT NOT NULL,
        UNIQUE(exam_id,start_time),
        CONSTRAINT chk_slot_capacity CHECK(capacity>0),
        FOREIGN KEY(exam_id) REFERENCES exams(exam_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS labs(
        lab_id INT AUTO_INCREMENT PRIMARY KEY,
        lab_name VARCHAR(80) NOT NULL UNIQUE,
        capacity INT NOT NULL,
        CONSTRAINT chk_lab_capacity CHECK(capacity>0)
    )""",
    """CREATE TABLE IF NOT EXISTS computers(
        computer_id INT AUTO_INCREMENT PRIMARY KEY,
        lab_id INT NOT NULL,
        computer_no VARCHAR(30) NOT NULL,
        state ENUM('ACTIVE','MAINTENANCE') NOT NULL DEFAULT 'ACTIVE',
        UNIQUE(lab_id,computer_no),
        FOREIGN KEY(lab_id) REFERENCES labs(lab_id)
    )""",
    """CREATE TABLE IF NOT EXISTS requests(
        request_id INT AUTO_INCREMENT PRIMARY KEY,
        student_id INT NOT NULL,
        exam_id INT NOT NULL,
        slot_id INT NOT NULL,
        priority TINYINT NOT NULL,
        request_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status ENUM('READY','WAITING','ALLOCATED','COMPLETED','CANCELLED') NOT NULL DEFAULT 'READY',
        CONSTRAINT chk_request_priority CHECK(priority BETWEEN 1 AND 3),
        FOREIGN KEY(student_id) REFERENCES students(student_id),
        FOREIGN KEY(exam_id) REFERENCES exams(exam_id),
        FOREIGN KEY(slot_id) REFERENCES slots(slot_id)
    )""",
    """CREATE TABLE IF NOT EXISTS allocations(
        allocation_id INT AUTO_INCREMENT PRIMARY KEY,
        request_id INT NOT NULL UNIQUE,
        slot_id INT NOT NULL,
        computer_id INT NOT NULL,
        status ENUM('ALLOCATED','COMPLETED','CANCELLED') NOT NULL DEFAULT 'ALLOCATED',
        allocated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(request_id) REFERENCES requests(request_id),
        FOREIGN KEY(slot_id) REFERENCES slots(slot_id),
        FOREIGN KEY(computer_id) REFERENCES computers(computer_id),
        KEY idx_slot_computer(slot_id,computer_id)
    )"""
]

def get_db_connection(database_name=None):
    db_to_use = Config.MYSQL_DB if database_name is None else database_name
    ports_to_try = [Config.MYSQL_PORT]
    last_err = None
    for p in ports_to_try:
        try:
            conn = pymysql.connect(
                host=Config.MYSQL_HOST,
                user=Config.MYSQL_USER,
                password=Config.MYSQL_PASSWORD,
                port=p,
                database=db_to_use,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True
            )
            Config.MYSQL_PORT = p
            return conn
        except pymysql.err.OperationalError as e:
            last_err = e
            if e.args and e.args[0] == 2003:
                continue
            raise
    raise last_err

def init_db():
    """Ensure database, tables, and default seed admin exist."""
    # First connect without specifying database to create labsync if missing
    conn = get_db_connection(database_name="")
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{Config.MYSQL_DB}`")
    conn.close()

    # Connect with database and create all tables
    conn = get_db_connection()
    with conn.cursor() as cur:
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)

        try:
            cur.execute("CREATE INDEX idx_schedule ON requests(status,priority,request_time)")
        except Exception:
            pass

        # Migrate allocations unique constraint on (slot_id, computer_id) if present
        # This allows computers to be re-allocated in a slot after previous allocations are CANCELLED or COMPLETED
        try:
            cur.execute("""
                SELECT INDEX_NAME, NON_UNIQUE 
                FROM information_schema.STATISTICS 
                WHERE TABLE_SCHEMA = DATABASE() 
                  AND TABLE_NAME = 'allocations' 
                  AND INDEX_NAME = 'slot_id'
            """)
            idx = cur.fetchone()
            if idx and idx['NON_UNIQUE'] == 0:
                cur.execute("ALTER TABLE allocations ADD INDEX idx_alloc_slot (slot_id)")
                cur.execute("ALTER TABLE allocations DROP INDEX slot_id")
                cur.execute("ALTER TABLE allocations ADD INDEX idx_alloc_slot_pc (slot_id, computer_id)")
        except Exception:
            pass

        # Check if default admin exists; if not, create one
        cur.execute("SELECT COUNT(*) AS count FROM admins")
        res = cur.fetchone()
        if res and res['count'] == 0:
            default_admin_hash = generate_password_hash("admin123")
            cur.execute(
                "INSERT INTO admins (name, email, password_hash) VALUES (%s, %s, %s)",
                ("Administrator", "admin@labsync.local", default_admin_hash)
            )

    conn.close()

