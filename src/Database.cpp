#include "Database.h"

#if __has_include(<jdbc/mysql_driver.h>)
    #include <jdbc/mysql_driver.h>
#elif __has_include(<mysql_driver.h>)
    #include <mysql_driver.h>
#endif

void Database::initSchema(const std::string& schema) {
    if (!con) return;
    auto stmt = std::unique_ptr<sql::Statement>(con->createStatement());

    // Ensure database exists and select it
    stmt->execute("CREATE DATABASE IF NOT EXISTS `" + schema + "`");
    con->setSchema(schema);

    // Ensure all tables exist
    stmt->execute(
        "CREATE TABLE IF NOT EXISTS students("
        " student_id INT AUTO_INCREMENT PRIMARY KEY,"
        " name VARCHAR(100) NOT NULL,"
        " email VARCHAR(120) NOT NULL UNIQUE,"
        " password_hash VARCHAR(255) NOT NULL"
        ")"
    );

    stmt->execute(
        "CREATE TABLE IF NOT EXISTS admins("
        " admin_id INT AUTO_INCREMENT PRIMARY KEY,"
        " name VARCHAR(100) NOT NULL,"
        " email VARCHAR(120) NOT NULL UNIQUE,"
        " password_hash VARCHAR(255) NOT NULL"
        ")"
    );

    stmt->execute(
        "CREATE TABLE IF NOT EXISTS exams("
        " exam_id INT AUTO_INCREMENT PRIMARY KEY,"
        " exam_name VARCHAR(120) NOT NULL,"
        " subject_code VARCHAR(30) NOT NULL,"
        " exam_date DATE NOT NULL,"
        " priority TINYINT NOT NULL DEFAULT 2,"
        " CONSTRAINT chk_exam_priority CHECK(priority BETWEEN 1 AND 3)"
        ")"
    );

    stmt->execute(
        "CREATE TABLE IF NOT EXISTS slots("
        " slot_id INT AUTO_INCREMENT PRIMARY KEY,"
        " exam_id INT NOT NULL,"
        " start_time TIME NOT NULL,"
        " end_time TIME NOT NULL,"
        " capacity INT NOT NULL,"
        " UNIQUE(exam_id,start_time),"
        " CONSTRAINT chk_slot_capacity CHECK(capacity>0),"
        " FOREIGN KEY(exam_id) REFERENCES exams(exam_id) ON DELETE CASCADE"
        ")"
    );

    stmt->execute(
        "CREATE TABLE IF NOT EXISTS labs("
        " lab_id INT AUTO_INCREMENT PRIMARY KEY,"
        " lab_name VARCHAR(80) NOT NULL UNIQUE,"
        " capacity INT NOT NULL,"
        " CONSTRAINT chk_lab_capacity CHECK(capacity>0)"
        ")"
    );

    stmt->execute(
        "CREATE TABLE IF NOT EXISTS computers("
        " computer_id INT AUTO_INCREMENT PRIMARY KEY,"
        " lab_id INT NOT NULL,"
        " computer_no VARCHAR(30) NOT NULL,"
        " state ENUM('ACTIVE','MAINTENANCE') NOT NULL DEFAULT 'ACTIVE',"
        " UNIQUE(lab_id,computer_no),"
        " FOREIGN KEY(lab_id) REFERENCES labs(lab_id)"
        ")"
    );

    stmt->execute(
        "CREATE TABLE IF NOT EXISTS requests("
        " request_id INT AUTO_INCREMENT PRIMARY KEY,"
        " student_id INT NOT NULL,"
        " exam_id INT NOT NULL,"
        " slot_id INT NOT NULL,"
        " priority TINYINT NOT NULL,"
        " request_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " status ENUM('READY','WAITING','ALLOCATED','COMPLETED','CANCELLED') NOT NULL DEFAULT 'READY',"
        " CONSTRAINT chk_request_priority CHECK(priority BETWEEN 1 AND 3),"
        " FOREIGN KEY(student_id) REFERENCES students(student_id),"
        " FOREIGN KEY(exam_id) REFERENCES exams(exam_id),"
        " FOREIGN KEY(slot_id) REFERENCES slots(slot_id)"
        ")"
    );

    stmt->execute(
        "CREATE TABLE IF NOT EXISTS allocations("
        " allocation_id INT AUTO_INCREMENT PRIMARY KEY,"
        " request_id INT NOT NULL UNIQUE,"
        " slot_id INT NOT NULL,"
        " computer_id INT NOT NULL,"
        " status ENUM('ALLOCATED','COMPLETED','CANCELLED') NOT NULL DEFAULT 'ALLOCATED',"
        " allocated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " FOREIGN KEY(request_id) REFERENCES requests(request_id),"
        " FOREIGN KEY(slot_id) REFERENCES slots(slot_id),"
        " FOREIGN KEY(computer_id) REFERENCES computers(computer_id),"
        " KEY idx_slot_computer(slot_id,computer_id)"
        ")"
    );

    try {
        stmt->execute("CREATE INDEX idx_schedule ON requests(status,priority,request_time)");
    } catch (...) {
        // Index already exists, ignore
    }
}

Database::Database(
    const std::string& host,
    const std::string& user,
    const std::string& pass,
    const std::string& schema
){
    sql::mysql::MySQL_Driver* driver = sql::mysql::get_mysql_driver_instance();

    std::string hostname = "127.0.0.1";
    int port = 3309;

    std::string h = host;
    const std::string prefix = "tcp://";
    if (h.rfind(prefix, 0) == 0) {
        h = h.substr(prefix.length());
    }
    auto colonPos = h.find(':');
    if (colonPos != std::string::npos) {
        hostname = h.substr(0, colonPos);
        try {
            port = std::stoi(h.substr(colonPos + 1));
        } catch (...) {
            port = 3309;
        }
    } else if (!h.empty()) {
        hostname = h;
    }

    std::string url = "tcp://" + hostname + ":" + std::to_string(port);

    con.reset(driver->connect(url, user, pass));
    initSchema(schema);
}

Database::~Database() = default;

Database::Database(Database&&) noexcept = default;

Database& Database::operator=(Database&&) noexcept = default;

sql::Connection* Database::get() const {
    return con.get();
}

bool Database::ok() const {
    return con && !con->isClosed();
}

