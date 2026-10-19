#include "LabSyncService.h"
#include "Scheduler.h"
#include "DeadlockPrevention.h"

#include <iostream>
#include <iomanip>
#include <limits>
#include <memory>
#include <vector>
#include <string>

using namespace std;

static void nl() {
    cin.ignore(numeric_limits<streamsize>::max(), '\n');
}

static bool readInt(const string& prompt, int& val) {
    cout << prompt;
    while (!(cin >> val)) {
        if (cin.eof()) return false;
        cin.clear();
        cin.ignore(numeric_limits<streamsize>::max(), '\n');
        cout << "Invalid input. Please enter a valid number: ";
    }
    return true;
}

static string priorityName(int p) {
    return p == 1 ? "HIGH" : p == 2 ? "NORMAL" : "LOW";
}

// ==================== STUDENT REGISTRATION ====================

void LabSyncService::registerStudent() {
    nl();

    string name, email, password;

    cout << "Name: ";
    getline(cin, name);
    if (name.empty()) {
        cout << "Name cannot be empty.\n";
        return;
    }

    cout << "Email: ";
    getline(cin, email);
    if (email.empty()) {
        cout << "Email cannot be empty.\n";
        return;
    }

    cout << "Password: ";
    getline(cin, password);
    if (password.empty()) {
        cout << "Password cannot be empty.\n";
        return;
    }

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "INSERT INTO students(name,email,password_hash) VALUES(?,?,?)"
            )
        );

        ps->setString(1, name);
        ps->setString(2, email);
        ps->setString(3, password);
        ps->executeUpdate();

        auto st = unique_ptr<sql::Statement>(
            db.get()->createStatement()
        );

        auto rs = unique_ptr<sql::ResultSet>(
            st->executeQuery("SELECT LAST_INSERT_ID() id")
        );

        rs->next();

        cout << "\nRegistered successfully! Student ID: "
             << rs->getInt("id") << "\n";

    } catch (sql::SQLException& e) {
        if (e.getErrorCode() == 1062) {
            cout << "Registration failed: An account with email '" << email << "' already exists.\n";
        } else {
            cout << "Registration failed: " << e.what() << "\n";
        }
    }
}

// ==================== ADD EXAM ====================

void LabSyncService::addExam() {
    nl();

    string name, code, date;
    int pr = 0;

    cout << "Exam name: ";
    getline(cin, name);
    if (name.empty()) {
        cout << "Exam name cannot be empty.\n";
        return;
    }

    cout << "Subject code: ";
    getline(cin, code);
    if (code.empty()) {
        cout << "Subject code cannot be empty.\n";
        return;
    }

    cout << "Exam date (YYYY-MM-DD): ";
    getline(cin, date);
    if (date.empty()) {
        cout << "Exam date cannot be empty.\n";
        return;
    }

    if (!readInt("Priority (1 High, 2 Normal, 3 Low): ", pr)) return;

    if (pr < 1 || pr > 3) {
        cout << "Invalid priority. Must be 1, 2, or 3.\n";
        return;
    }

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "INSERT INTO exams(exam_name,subject_code,exam_date,priority) "
                "VALUES(?,?,?,?)"
            )
        );

        ps->setString(1, name);
        ps->setString(2, code);
        ps->setString(3, date);
        ps->setInt(4, pr);

        ps->executeUpdate();

        cout << "\nExam added successfully.\n";

    } catch (sql::SQLException& e) {
        cout << "Failed to add exam: " << e.what() << "\n";
    }
}

// ==================== VIEW EXAMS ====================

void LabSyncService::listExams() {
    try {
        auto st = unique_ptr<sql::Statement>(
            db.get()->createStatement()
        );

        auto r = unique_ptr<sql::ResultSet>(
            st->executeQuery(
                "SELECT exam_id,exam_name,subject_code,exam_date,priority "
                "FROM exams ORDER BY exam_date,exam_id"
            )
        );

        cout << "\nID | Exam | Code | Date | Priority\n";
        bool found = false;
        while (r->next()) {
            found = true;
            cout << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << " | "
                 << r->getString(4) << " | "
                 << priorityName(r->getInt(5)) << "\n";
        }
        if (!found) {
            cout << "No exams found.\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== ADD SLOT ====================

void LabSyncService::addSlot() {
    listExams();

    int exam = 0, cap = 0;
    string start, end;

    if (!readInt("Exam ID: ", exam)) return;

    cout << "Start (HH:MM:SS): ";
    cin >> start;

    cout << "End (HH:MM:SS): ";
    cin >> end;

    if (!readInt("Capacity: ", cap)) return;

    if (cap <= 0) {
        cout << "Capacity must be greater than 0.\n";
        return;
    }

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "INSERT INTO slots(exam_id,start_time,end_time,capacity) "
                "VALUES(?,?,?,?)"
            )
        );

        ps->setInt(1, exam);
        ps->setString(2, start);
        ps->setString(3, end);
        ps->setInt(4, cap);

        ps->executeUpdate();

        cout << "\nSlot added successfully.\n";

    } catch (sql::SQLException& e) {
        cout << "Failed to add slot: " << e.what() << "\n";
    }
}

// ==================== VIEW SLOTS ====================

void LabSyncService::listSlots() {
    try {
        auto st = unique_ptr<sql::Statement>(
            db.get()->createStatement()
        );

        auto r = unique_ptr<sql::ResultSet>(
            st->executeQuery(
                "SELECT s.slot_id,e.exam_name,s.start_time,s.end_time,s.capacity "
                "FROM slots s "
                "JOIN exams e ON e.exam_id=s.exam_id "
                "ORDER BY e.exam_id,s.start_time"
            )
        );

        cout << "\nSlot | Exam | Time | Capacity\n";
        bool found = false;
        while (r->next()) {
            found = true;
            cout << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << "-"
                 << r->getString(4) << " | "
                 << r->getInt(5) << "\n";
        }
        if (!found) {
            cout << "No slots found.\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== ADD LAB ====================

void LabSyncService::addLab() {
    nl();

    string name;
    int cap = 0;

    cout << "Lab name: ";
    getline(cin, name);
    if (name.empty()) {
        cout << "Lab name cannot be empty.\n";
        return;
    }

    if (!readInt("Capacity: ", cap)) return;

    if (cap <= 0) {
        cout << "Capacity must be greater than 0.\n";
        return;
    }

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "INSERT INTO labs(lab_name,capacity) VALUES(?,?)"
            )
        );

        ps->setString(1, name);
        ps->setInt(2, cap);

        ps->executeUpdate();

        auto idQuery = unique_ptr<sql::Statement>(db.get()->createStatement());
        auto idRes = unique_ptr<sql::ResultSet>(idQuery->executeQuery("SELECT LAST_INSERT_ID()"));
        if (idRes->next()) {
            cout << "\nLab '" << name << "' added successfully! Lab ID: " << idRes->getInt(1)
                 << " (Capacity: " << cap << ").\n";
        } else {
            cout << "\nLab added successfully.\n";
        }

    } catch (sql::SQLException& e) {
        cout << "Failed to add lab: " << e.what() << "\n";
    }
}

// ==================== LIST LABS ====================

void LabSyncService::listLabs() {
    try {
        auto st = unique_ptr<sql::Statement>(
            db.get()->createStatement()
        );

        auto r = unique_ptr<sql::ResultSet>(
            st->executeQuery(
                "SELECT l.lab_id, l.lab_name, l.capacity, "
                "COUNT(c.computer_id) AS registered_pcs "
                "FROM labs l "
                "LEFT JOIN computers c ON c.lab_id = l.lab_id "
                "GROUP BY l.lab_id, l.lab_name, l.capacity "
                "ORDER BY l.lab_id"
            )
        );

        cout << "\n===== REGISTERED LABS =====\n";
        cout << left << setw(8) << "Lab ID" << " | "
             << setw(20) << "Lab Name" << " | "
             << setw(10) << "Capacity" << " | "
             << "PCs Registered\n";
        cout << "---------------------------------------------------------\n";

        bool found = false;
        while (r->next()) {
            found = true;
            cout << left << setw(8) << r->getInt(1) << " | "
                 << setw(20) << r->getString(2) << " | "
                 << setw(10) << r->getInt(3) << " | "
                 << r->getInt(4) << "\n";
        }

        if (!found) {
            cout << "No labs created yet. Please add a lab first.\n";
        }
    } catch (sql::SQLException& e) {
        cout << "Error listing labs: " << e.what() << "\n";
    }
}

// ==================== BULK ADD COMPUTERS ====================

void LabSyncService::addComputer() {
    listLabs();

    int lab = 0, quantity = 0;

    cout << "\n===== BULK COMPUTER REGISTRATION =====\n";

    if (!readInt("Enter Lab ID: ", lab)) return;
    if (!readInt("Number of computers to add: ", quantity)) return;

    if (lab <= 0 || quantity <= 0 || quantity > 1000) {
        cout << "Quantity must be between 1 and 1000.\n";
        return;
    }

    try {
        auto info = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "SELECT l.capacity, "
                "(SELECT COUNT(*) FROM computers c "
                "WHERE c.lab_id=l.lab_id) AS registered "
                "FROM labs l WHERE l.lab_id=?"
            )
        );

        info->setInt(1, lab);

        auto result = unique_ptr<sql::ResultSet>(
            info->executeQuery()
        );

        if (!result->next()) {
            cout << "Lab ID not found.\n";
            return;
        }

        int capacity = result->getInt(1);
        int registered = result->getInt(2);

        if (quantity > capacity - registered) {
            cout << "Lab capacity: " << capacity << "\n";
            cout << "Already registered: " << registered << "\n";
            cout << "Available spaces: "
                 << capacity - registered << "\n";
            return;
        }

        result.reset();
        info.reset();

        db.get()->setAutoCommit(false);

        try {
            auto check = unique_ptr<sql::PreparedStatement>(
                db.get()->prepareStatement(
                    "SELECT COUNT(*) FROM computers "
                    "WHERE lab_id=? AND computer_no=?"
                )
            );

            auto insert = unique_ptr<sql::PreparedStatement>(
                db.get()->prepareStatement(
                    "INSERT INTO computers(lab_id,computer_no,state) "
                    "VALUES(?,?,'ACTIVE')"
                )
            );

            int added = 0;
            int number = 1;

            while (added < quantity) {
                string pc = "PC" + to_string(number++);

                check->setInt(1, lab);
                check->setString(2, pc);

                auto existing = unique_ptr<sql::ResultSet>(
                    check->executeQuery()
                );

                existing->next();

                bool taken = existing->getInt(1) != 0;
                existing.reset();

                if (taken) {
                    continue;
                }

                insert->setInt(1, lab);
                insert->setString(2, pc);
                insert->executeUpdate();

                cout << pc << " added successfully.\n";
                added++;
            }

            db.get()->commit();
            db.get()->setAutoCommit(true);

            cout << "\nSuccessfully registered "
                 << added << " ACTIVE computers in Lab "
                 << lab << "!\n";

        } catch (...) {
            db.get()->rollback();
            db.get()->setAutoCommit(true);
            throw;
        }

    } catch (sql::SQLException& e) {
        cout << "Bulk registration failed: "
             << e.what() << "\n";
    }
}

// ==================== VIEW STUDENTS ====================

void LabSyncService::listStudents() {
    try {
        auto st = unique_ptr<sql::Statement>(
            db.get()->createStatement()
        );

        auto r = unique_ptr<sql::ResultSet>(
            st->executeQuery(
                "SELECT student_id,name,email "
                "FROM students ORDER BY student_id"
            )
        );

        cout << "\nID | Name | Email\n";
        bool found = false;
        while (r->next()) {
            found = true;
            cout << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << "\n";
        }
        if (!found) {
            cout << "No students registered.\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== BOOK SLOT ====================

void LabSyncService::bookSlot() {
    int sid = 0, slot = 0;

    listExams();
    listSlots();

    if (!readInt("Student ID: ", sid)) return;
    if (!readInt("Slot ID: ", slot)) return;

    if (sid <= 0 || slot <= 0) {
        cout << "Invalid Student ID or Slot ID.\n";
        return;
    }

    try {
        // Verify student exists
        auto studentCheck = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement("SELECT student_id FROM students WHERE student_id=?")
        );
        studentCheck->setInt(1, sid);
        auto sRes = unique_ptr<sql::ResultSet>(studentCheck->executeQuery());
        if (!sRes->next()) {
            cout << "\nStudent ID " << sid << " not found. Please register first.\n";
            return;
        }

        // Find the exam associated with the selected slot.
        auto examQuery = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "SELECT exam_id FROM slots WHERE slot_id=?"
            )
        );

        examQuery->setInt(1, slot);

        auto examResult = unique_ptr<sql::ResultSet>(
            examQuery->executeQuery()
        );

        if (!examResult->next()) {
            cout << "\nInvalid slot ID.\n";
            return;
        }

        int examId = examResult->getInt(1);

        // Check if this student already booked this exam.
        auto check = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "SELECT status FROM requests "
                "WHERE student_id=? AND exam_id=? "
                "AND status <> 'CANCELLED' "
                "LIMIT 1"
            )
        );

        check->setInt(1, sid);
        check->setInt(2, examId);

        auto result = unique_ptr<sql::ResultSet>(
            check->executeQuery()
        );

        if (result->next()) {
            cout << "\nBooking rejected!\n";
            cout << "You have already booked this exam.\n";
            cout << "Existing status: "
                 << result->getString(1) << "\n";
            return;
        }

        // No duplicate found, proceed with booking.
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "INSERT INTO requests"
                "(student_id,exam_id,slot_id,priority) "
                "SELECT ?,s.exam_id,s.slot_id,e.priority "
                "FROM slots s "
                "JOIN exams e ON e.exam_id=s.exam_id "
                "WHERE s.slot_id=?"
            )
        );

        ps->setInt(1, sid);
        ps->setInt(2, slot);

        int n = ps->executeUpdate();

        if (!n) {
            cout << "\nFailed to create booking for slot " << slot << ".\n";
            return;
        }

        cout << "\nBooking successful!\n";
        cout << "Status: READY (Queued for allocation)\n";

    } catch (sql::SQLException& e) {
        cout << "Booking failed: " << e.what() << "\n";
    }
}

// ==================== MY BOOKINGS ====================

void LabSyncService::myBookings() {
    int sid = 0;

    if (!readInt("Student ID: ", sid)) return;

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "SELECT r.request_id,e.exam_name,s.start_time,s.end_time,"
                "r.priority,r.status,l.lab_name,c.computer_no "
                "FROM requests r "
                "JOIN exams e ON e.exam_id=r.exam_id "
                "JOIN slots s ON s.slot_id=r.slot_id "
                "LEFT JOIN allocations a ON a.request_id=r.request_id "
                "AND a.status='ALLOCATED' "
                "LEFT JOIN computers c ON c.computer_id=a.computer_id "
                "LEFT JOIN labs l ON l.lab_id=c.lab_id "
                "WHERE r.student_id=? "
                "ORDER BY r.request_time DESC"
            )
        );

        ps->setInt(1, sid);

        auto r = unique_ptr<sql::ResultSet>(
            ps->executeQuery()
        );

        cout << "\nRID | Exam | Slot Time | Priority | Status | Lab | PC\n";
        bool found = false;
        while (r->next()) {
            found = true;
            cout << "R" << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << "-"
                 << r->getString(4) << " | "
                 << priorityName(r->getInt(5)) << " | "
                 << r->getString(6) << " | "
                 << (r->isNull(7) ? "--" : r->getString(7))
                 << " | "
                 << (r->isNull(8) ? "--" : r->getString(8))
                 << "\n";
        }
        if (!found) {
            cout << "No bookings found for Student ID " << sid << ".\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== CANCEL BOOKING ====================

void LabSyncService::cancelBooking() {
    int rid = 0;

    if (!readInt("Request ID: ", rid)) return;

    if (rid <= 0) {
        cout << "Invalid Request ID.\n";
        return;
    }

    try {
        db.get()->setAutoCommit(false);

        auto p1 = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "UPDATE allocations SET status='CANCELLED' "
                "WHERE request_id=? AND status='ALLOCATED'"
            )
        );

        p1->setInt(1, rid);
        p1->executeUpdate();

        auto p2 = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "UPDATE requests SET status='CANCELLED' "
                "WHERE request_id=? "
                "AND status IN ('READY','WAITING','ALLOCATED')"
            )
        );

        p2->setInt(1, rid);
        int n = p2->executeUpdate();

        db.get()->commit();
        db.get()->setAutoCommit(true);

        cout << (n ? "\nBooking cancelled successfully.\n"
                   : "\nNo cancellable booking found for this Request ID.\n");

    } catch (sql::SQLException& e) {
        db.get()->rollback();
        db.get()->setAutoCommit(true);
        cout << "Cancellation failed: " << e.what() << "\n";
    }
}

// ==================== VIEW BOOKINGS ====================

void LabSyncService::listBookings() {
    try {
        auto st = unique_ptr<sql::Statement>(
            db.get()->createStatement()
        );

        auto r = unique_ptr<sql::ResultSet>(
            st->executeQuery(
                "SELECT r.request_id,st.name,e.exam_name,"
                "s.start_time,s.end_time,r.priority,"
                "r.request_time,r.status,l.lab_name,c.computer_no "
                "FROM requests r "
                "JOIN students st ON st.student_id=r.student_id "
                "JOIN exams e ON e.exam_id=r.exam_id "
                "JOIN slots s ON s.slot_id=r.slot_id "
                "LEFT JOIN allocations a ON a.request_id=r.request_id "
                "AND a.status='ALLOCATED' "
                "LEFT JOIN computers c ON c.computer_id=a.computer_id "
                "LEFT JOIN labs l ON l.lab_id=c.lab_id "
                "ORDER BY r.priority,r.request_time"
            )
        );

        cout << "\nRID | Student | Exam | Slot | P | Status | Lab | PC\n";
        bool found = false;
        while (r->next()) {
            found = true;
            cout << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << " | "
                 << r->getString(4) << "-"
                 << r->getString(5) << " | "
                 << priorityName(r->getInt(6)) << " | "
                 << r->getString(8) << " | "
                 << (r->isNull(9) ? "--" : r->getString(9))
                 << " | "
                 << (r->isNull(10) ? "--" : r->getString(10))
                 << "\n";
        }
        if (!found) {
            cout << "No bookings recorded.\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== PRIORITY + FCFS SCHEDULER ====================

// ==================== COMPUTER AVAILABILITY ====================

void LabSyncService::computerAvailability() {
    int slot = 0;

    listSlots();

    if (!readInt("Slot ID: ", slot)) return;

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "SELECT l.lab_name, c.computer_no, c.state, "
                "CASE "
                "WHEN c.state='MAINTENANCE' THEN 'MAINTENANCE' "
                "WHEN a.status='ALLOCATED' THEN 'OCCUPIED' "
                "ELSE 'AVAILABLE' END AS availability, "
                "st.name AS student_name, "
                "r.request_id "
                "FROM computers c "
                "JOIN labs l ON l.lab_id=c.lab_id "
                "LEFT JOIN allocations a ON a.computer_id=c.computer_id "
                "AND a.slot_id=? AND a.status='ALLOCATED' "
                "LEFT JOIN requests r ON r.request_id=a.request_id "
                "LEFT JOIN students st ON st.student_id=r.student_id "
                "ORDER BY l.lab_id, c.computer_id"
            )
        );

        ps->setInt(1, slot);

        auto r = unique_ptr<sql::ResultSet>(
            ps->executeQuery()
        );

        cout << "\n"
             << left << setw(20) << "Lab Name" << " | "
             << setw(12) << "Computer" << " | "
             << setw(12) << "Status" << " | "
             << "Assigned Student\n";
        cout << "---------------------------------------------------------------------------\n";

        bool found = false;
        while (r->next()) {
            found = true;
            string labName = r->getString("lab_name");
            string pcNo = r->getString("computer_no");
            string status = r->getString("availability");
            string assigned = "--";

            if (status == "OCCUPIED" && !r->isNull("student_name")) {
                assigned = r->getString("student_name") + " (Request #" + to_string(r->getInt("request_id")) + ")";
            }

            cout << left << setw(20) << labName << " | "
                 << setw(12) << pcNo << " | "
                 << setw(12) << status << " | "
                 << assigned << "\n";
        }
        if (!found) {
            cout << "No computers found for this slot.\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== COMPLETE SESSION ====================

void LabSyncService::completeSession() {
    int rid = 0;

    if (!readInt("Request ID: ", rid)) return;

    try {
        db.get()->setAutoCommit(false);

        auto a = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "UPDATE allocations SET status='COMPLETED' "
                "WHERE request_id=? AND status='ALLOCATED'"
            )
        );

        a->setInt(1, rid);
        a->executeUpdate();

        auto r = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "UPDATE requests SET status='COMPLETED' "
                "WHERE request_id=? AND status='ALLOCATED'"
            )
        );

        r->setInt(1, rid);
        int n = r->executeUpdate();

        db.get()->commit();
        db.get()->setAutoCommit(true);

        cout << (n ? "\nSession completed successfully.\n"
                   : "\nAllocated request not found or not in ALLOCATED state.\n");

    } catch (sql::SQLException& e) {
        db.get()->rollback();
        db.get()->setAutoCommit(true);
        cout << e.what() << "\n";
    }
}
