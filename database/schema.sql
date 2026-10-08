CREATE DATABASE IF NOT EXISTS labsync;
USE labsync;

CREATE TABLE IF NOT EXISTS students(
 student_id INT AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(100) NOT NULL,
 email VARCHAR(120) NOT NULL UNIQUE,
 password_hash VARCHAR(255) NOT NULL
);
CREATE TABLE IF NOT EXISTS admins(
 admin_id INT AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(100) NOT NULL,
 email VARCHAR(120) NOT NULL UNIQUE,
 password_hash VARCHAR(255) NOT NULL
);
CREATE TABLE IF NOT EXISTS exams(
 exam_id INT AUTO_INCREMENT PRIMARY KEY,
 exam_name VARCHAR(120) NOT NULL,
 subject_code VARCHAR(30) NOT NULL,
 exam_date DATE NOT NULL,
 priority TINYINT NOT NULL DEFAULT 2,
 CONSTRAINT chk_exam_priority CHECK(priority BETWEEN 1 AND 3)
);
CREATE TABLE IF NOT EXISTS slots(
 slot_id INT AUTO_INCREMENT PRIMARY KEY,
 exam_id INT NOT NULL,
 start_time TIME NOT NULL,
 end_time TIME NOT NULL,
 capacity INT NOT NULL,
 UNIQUE(exam_id,start_time),
 CONSTRAINT chk_slot_capacity CHECK(capacity>0),
 FOREIGN KEY(exam_id) REFERENCES exams(exam_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS labs(
 lab_id INT AUTO_INCREMENT PRIMARY KEY,
 lab_name VARCHAR(80) NOT NULL UNIQUE,
 capacity INT NOT NULL,
 CONSTRAINT chk_lab_capacity CHECK(capacity>0)
);
CREATE TABLE IF NOT EXISTS computers(
 computer_id INT AUTO_INCREMENT PRIMARY KEY,
 lab_id INT NOT NULL,
 computer_no VARCHAR(30) NOT NULL,
 state ENUM('ACTIVE','MAINTENANCE') NOT NULL DEFAULT 'ACTIVE',
 UNIQUE(lab_id,computer_no),
 FOREIGN KEY(lab_id) REFERENCES labs(lab_id)
);
CREATE TABLE IF NOT EXISTS requests(
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
);
CREATE TABLE IF NOT EXISTS allocations(
 allocation_id INT AUTO_INCREMENT PRIMARY KEY,
 request_id INT NOT NULL UNIQUE,
 slot_id INT NOT NULL,
 computer_id INT NOT NULL,
 status ENUM('ALLOCATED','COMPLETED','CANCELLED') NOT NULL DEFAULT 'ALLOCATED',
 allocated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(request_id) REFERENCES requests(request_id),
 FOREIGN KEY(slot_id) REFERENCES slots(slot_id),
 FOREIGN KEY(computer_id) REFERENCES computers(computer_id),
 UNIQUE(slot_id,computer_id)
);
CREATE INDEX idx_schedule ON requests(status,priority,request_time);
