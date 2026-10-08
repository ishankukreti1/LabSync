
#include "LabSyncService.h"

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

static string priorityName(int p) {
    return p == 1 ? "HIGH" : p == 2 ? "NORMAL" : "LOW";
}

// ==================== STUDENT REGISTRATION ====================

void LabSyncService::registerStudent() {
    nl();

    string name, email, password;

    cout << "Name: ";
    getline(cin, name);

    cout << "Email: ";
    getline(cin, email);

    cout << "Password: ";
    getline(cin, password);

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

        cout << "Registered. Student ID: "
             << rs->getInt("id") << "\n";

    } catch (sql::SQLException& e) {
        cout << "Registration failed: " << e.what() << "\n";
    }
}

// ==================== ADD EXAM ====================

void LabSyncService::addExam() {
    nl();

    string name, code, date;
    int pr;

    cout << "Exam name: ";
    getline(cin, name);

    cout << "Subject code: ";
    getline(cin, code);

    cout << "Exam date (YYYY-MM-DD): ";
    getline(cin, date);

    cout << "Priority (1 High, 2 Normal, 3 Low): ";
    cin >> pr;

    if (pr < 1 || pr > 3) {
        cout << "Invalid priority.\n";
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

        cout << "Exam added.\n";

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
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

        while (r->next()) {
            cout << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << " | "
                 << r->getString(4) << " | "
                 << priorityName(r->getInt(5)) << "\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== ADD SLOT ====================

void LabSyncService::addSlot() {
    listExams();

    int exam, cap;
    string start, end;

    cout << "Exam ID: ";
    cin >> exam;

    cout << "Start (HH:MM:SS): ";
    cin >> start;

    cout << "End (HH:MM:SS): ";
    cin >> end;

    cout << "Capacity: ";
    cin >> cap;

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

        cout << "Slot added.\n";

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
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

        while (r->next()) {
            cout << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << "-"
                 << r->getString(4) << " | "
                 << r->getInt(5) << "\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== ADD LAB ====================

void LabSyncService::addLab() {
    nl();

    string name;
    int cap;

    cout << "Lab name: ";
    getline(cin, name);

    cout << "Capacity: ";
    cin >> cap;

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "INSERT INTO labs(lab_name,capacity) VALUES(?,?)"
            )
        );

        ps->setString(1, name);
        ps->setInt(2, cap);

        ps->executeUpdate();

        cout << "Lab added.\n";

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== BULK ADD COMPUTERS ====================

void LabSyncService::addComputer() {
    int lab, quantity;

    cout << "\n===== BULK COMPUTER REGISTRATION =====\n";

    cout << "Lab ID: ";
    if (!(cin >> lab)) {
        cin.clear();
        nl();
        cout << "Invalid Lab ID.\n";
        return;
    }

    cout << "Number of computers to add: ";
    if (!(cin >> quantity)) {
        cin.clear();
        nl();
        cout << "Invalid quantity.\n";
        return;
    }

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

        while (r->next()) {
            cout << r->getInt(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(3) << "\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== BOOK SLOT ====================

void LabSyncService::bookSlot() {
    int sid, slot;

    listExams();
    listSlots();

    cout << "Student ID: ";
    cin >> sid;

    cout << "Slot ID: ";
    cin >> slot;

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "INSERT INTO requests(student_id,exam_id,slot_id,priority) "
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
            cout << "Invalid slot.\n";
            return;
        }

        cout << "Booking request saved in MySQL.\n";
        cout << "Status READY; priority inherited from exam.\n";

    } catch (sql::SQLException& e) {
        cout << "Booking failed: " << e.what() << "\n";
    }
}

// ==================== MY BOOKINGS ====================

void LabSyncService::myBookings() {
    int sid;

    cout << "Student ID: ";
    cin >> sid;

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

        while (r->next()) {
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

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== CANCEL BOOKING ====================

void LabSyncService::cancelBooking() {
    int rid;

    cout << "Request ID: ";
    cin >> rid;

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

        cout << (n ? "Booking cancelled.\n"
                   : "Nothing cancellable found.\n");

    } catch (sql::SQLException& e) {
        db.get()->rollback();
        db.get()->setAutoCommit(true);
        cout << e.what() << "\n";
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

        while (r->next()) {
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

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== PRIORITY + FCFS SCHEDULER ====================

void LabSyncService::runScheduler() {
    try {
        auto q = unique_ptr<sql::Statement>(
            db.get()->createStatement()
        );

        auto rr = unique_ptr<sql::ResultSet>(
            q->executeQuery(
                "SELECT request_id FROM requests "
                "WHERE status IN ('READY','WAITING') "
                "ORDER BY priority ASC,request_time ASC"
            )
        );

        vector<int> ids;

        while (rr->next()) {
            ids.push_back(rr->getInt(1));
        }

        for (int rid : ids) {
            try {
                db.get()->setAutoCommit(false);

                auto lock = unique_ptr<sql::PreparedStatement>(
                    db.get()->prepareStatement(
                        "SELECT r.slot_id,s.capacity "
                        "FROM requests r "
                        "JOIN slots s ON s.slot_id=r.slot_id "
                        "WHERE r.request_id=? "
                        "AND r.status IN ('READY','WAITING') "
                        "FOR UPDATE"
                    )
                );

                lock->setInt(1, rid);

                auto lr = unique_ptr<sql::ResultSet>(
                    lock->executeQuery()
                );

                if (!lr->next()) {
                    db.get()->rollback();
                    db.get()->setAutoCommit(true);
                    continue;
                }

                int slot = lr->getInt(1);
                int cap = lr->getInt(2);

                auto count = unique_ptr<sql::PreparedStatement>(
                    db.get()->prepareStatement(
                        "SELECT COUNT(*) n FROM allocations "
                        "WHERE slot_id=? AND status='ALLOCATED'"
                    )
                );

                count->setInt(1, slot);

                auto cr = unique_ptr<sql::ResultSet>(
                    count->executeQuery()
                );

                cr->next();

                if (cr->getInt(1) >= cap) {
                    auto w = unique_ptr<sql::PreparedStatement>(
                        db.get()->prepareStatement(
                            "UPDATE requests SET status='WAITING' "
                            "WHERE request_id=?"
                        )
                    );

                    w->setInt(1, rid);
                    w->executeUpdate();

                    db.get()->commit();
                    db.get()->setAutoCommit(true);
                    continue;
                }

                auto pc = unique_ptr<sql::PreparedStatement>(
                    db.get()->prepareStatement(
                        "SELECT c.computer_id FROM computers c "
                        "WHERE c.state='ACTIVE' "
                        "AND NOT EXISTS("
                        "SELECT 1 FROM allocations a "
                        "WHERE a.computer_id=c.computer_id "
                        "AND a.slot_id=? "
                        "AND a.status='ALLOCATED') "
                        "ORDER BY c.lab_id,c.computer_id "
                        "LIMIT 1 FOR UPDATE"
                    )
                );

                pc->setInt(1, slot);

                auto pr = unique_ptr<sql::ResultSet>(
                    pc->executeQuery()
                );

                if (!pr->next()) {
                    auto w = unique_ptr<sql::PreparedStatement>(
                        db.get()->prepareStatement(
                            "UPDATE requests SET status='WAITING' "
                            "WHERE request_id=?"
                        )
                    );

                    w->setInt(1, rid);
                    w->executeUpdate();

                    db.get()->commit();
                    db.get()->setAutoCommit(true);
                    continue;
                }

                int cid = pr->getInt(1);

                auto ins = unique_ptr<sql::PreparedStatement>(
                    db.get()->prepareStatement(
                        "INSERT INTO allocations("
                        "request_id,slot_id,computer_id,status) "
                        "VALUES(?,?,?,'ALLOCATED')"
                    )
                );

                ins->setInt(1, rid);
                ins->setInt(2, slot);
                ins->setInt(3, cid);
                ins->executeUpdate();

                auto u = unique_ptr<sql::PreparedStatement>(
                    db.get()->prepareStatement(
                        "UPDATE requests SET status='ALLOCATED' "
                        "WHERE request_id=?"
                    )
                );

                u->setInt(1, rid);
                u->executeUpdate();

                db.get()->commit();
                db.get()->setAutoCommit(true);

                cout << "Request " << rid
                     << " allocated to computer " << cid << ".\n";

            } catch (sql::SQLException& e) {
                db.get()->rollback();
                db.get()->setAutoCommit(true);

                cout << "Request " << rid
                     << " rolled back: " << e.what() << "\n";
            }
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== COMPUTER AVAILABILITY ====================

void LabSyncService::computerAvailability() {
    int slot;

    listSlots();

    cout << "Slot ID: ";
    cin >> slot;

    try {
        auto ps = unique_ptr<sql::PreparedStatement>(
            db.get()->prepareStatement(
                "SELECT l.lab_name,c.computer_no,c.state,"
                "CASE "
                "WHEN c.state='MAINTENANCE' THEN 'MAINTENANCE' "
                "WHEN EXISTS("
                "SELECT 1 FROM allocations a "
                "WHERE a.computer_id=c.computer_id "
                "AND a.slot_id=? "
                "AND a.status='ALLOCATED') "
                "THEN 'OCCUPIED' "
                "ELSE 'AVAILABLE' END availability "
                "FROM computers c "
                "JOIN labs l ON l.lab_id=c.lab_id "
                "ORDER BY l.lab_id,c.computer_id"
            )
        );

        ps->setInt(1, slot);

        auto r = unique_ptr<sql::ResultSet>(
            ps->executeQuery()
        );

        while (r->next()) {
            cout << r->getString(1) << " | "
                 << r->getString(2) << " | "
                 << r->getString(4) << "\n";
        }

    } catch (sql::SQLException& e) {
        cout << e.what() << "\n";
    }
}

// ==================== COMPLETE SESSION ====================

void LabSyncService::completeSession() {
    int rid;

    cout << "Request ID: ";
    cin >> rid;

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

        cout << (n ? "Session completed.\n"
                   : "Allocated request not found.\n");

    } catch (sql::SQLException& e) {
        db.get()->rollback();
        db.get()->setAutoCommit(true);
        cout << e.what() << "\n";
    }
}
