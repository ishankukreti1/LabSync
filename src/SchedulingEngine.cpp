#include "LabSyncService.h"
#include "Scheduler.h"
#include "DeadlockPrevention.h"
#include <iostream>
#include <memory>
#include <vector>
#include <string>
#include <algorithm>

using namespace std;

// One transaction per request. Lock ordering: request -> slot -> all labs (by lab_id)
// -> chosen computer. All schedulers use the same order; rollback releases all locks.
void LabSyncService::runScheduler() {
    try {
        auto q = unique_ptr<sql::Statement>(db.get()->createStatement());
        auto rr = unique_ptr<sql::ResultSet>(q->executeQuery(
            "SELECT request_id,student_id,exam_id,slot_id,priority,"
            "CAST(request_time AS CHAR) req_time,status FROM requests "
            "WHERE status IN ('READY','WAITING')"));
        vector<BookingRequest> requests;
        while (rr->next()) {
            BookingRequest r;
            r.id=rr->getInt("request_id"); r.studentId=rr->getInt("student_id");
            r.examId=rr->getInt("exam_id"); r.slotId=rr->getInt("slot_id");
            r.priority=rr->getInt("priority"); r.requestTime=rr->getString("req_time");
            r.status=rr->getString("status"); requests.push_back(r);
        }
        if (requests.empty()) {
            cout << "No pending requests in READY or WAITING status.\n";
            cout << "Scheduler completed: 0 allocated, 0 waiting.\n";
            return;
        }
        int allocated=0, waiting=0, failures=0, deadlocks=0;
        for (const auto& r : Scheduler::priorityFCFS(requests)) {
            // Retry MySQL's actual deadlock (1213) or lock wait timeout (1205).
            for (int attempt=0; attempt<3; ++attempt) {
                try {
                    db.get()->setAutoCommit(false);
                    auto lock=unique_ptr<sql::PreparedStatement>(db.get()->prepareStatement(
                        "SELECT r.slot_id,r.exam_id,s.capacity "
                        "FROM requests r JOIN slots s ON s.slot_id=r.slot_id "
                        "WHERE r.request_id=? AND r.status IN ('READY','WAITING') FOR UPDATE"));
                    lock->setInt(1,r.id);
                    auto lr=unique_ptr<sql::ResultSet>(lock->executeQuery());
                    if (!lr->next()) { db.get()->rollback(); db.get()->setAutoCommit(true); break; }
                    int slot=lr->getInt(1), exam=lr->getInt(2), cap=lr->getInt(3);
                    auto sl=unique_ptr<sql::PreparedStatement>(db.get()->prepareStatement(
                        "SELECT capacity FROM slots WHERE slot_id=? FOR UPDATE"));
                    sl->setInt(1,slot);
                    auto sr=unique_ptr<sql::ResultSet>(sl->executeQuery());
                    if (!sr->next()) { db.get()->rollback(); db.get()->setAutoCommit(true); break; }
                    cap=sr->getInt(1);
                    // Lock ALL lab rows in deterministic order. This serializes lab choice
                    // across different exam slots, not only within the same slot.
                    auto labs=unique_ptr<sql::Statement>(db.get()->createStatement());
                    auto labRows=unique_ptr<sql::ResultSet>(labs->executeQuery(
                        "SELECT lab_id FROM labs ORDER BY lab_id FOR UPDATE"));
                    vector<int> labIds;
                    while(labRows->next()) labIds.push_back(labRows->getInt(1));
                    auto count=unique_ptr<sql::PreparedStatement>(db.get()->prepareStatement(
                        "SELECT COUNT(*) FROM allocations WHERE slot_id=? AND status='ALLOCATED'"));
                    count->setInt(1,slot);
                    auto cr=unique_ptr<sql::ResultSet>(count->executeQuery()); cr->next();
                    int cid=0;
                    if (cr->getInt(1)<cap) {
                        // A lab belongs to one exam for the duration of overlapping slots.
                        // Historical COMPLETED/CANCELLED allocations do not reserve a lab.
                        auto pc=unique_ptr<sql::PreparedStatement>(db.get()->prepareStatement(
                            "SELECT c.computer_id FROM computers c "
                            "JOIN labs l ON l.lab_id=c.lab_id "
                            "JOIN slots target ON target.slot_id=? "
                            "JOIN exams te ON te.exam_id=target.exam_id "
                            "WHERE c.state='ACTIVE' "
                            "AND NOT EXISTS ("
                            " SELECT 1 FROM allocations a "
                            " JOIN computers occupied ON occupied.computer_id=a.computer_id "
                            " JOIN slots os ON os.slot_id=a.slot_id "
                            " JOIN exams oe ON oe.exam_id=os.exam_id "
                            " WHERE occupied.lab_id=c.lab_id AND a.status='ALLOCATED' "
                            " AND oe.exam_date=te.exam_date "
                            " AND os.start_time<target.end_time AND target.start_time<os.end_time "
                            " AND oe.exam_id<>te.exam_id) "
                            "AND NOT EXISTS ("
                            " SELECT 1 FROM allocations a "
                            " JOIN slots os ON os.slot_id=a.slot_id "
                            " JOIN exams oe ON oe.exam_id=os.exam_id "
                            " WHERE a.computer_id=c.computer_id AND a.status='ALLOCATED' "
                            " AND oe.exam_date=te.exam_date "
                            " AND os.start_time<target.end_time AND target.start_time<os.end_time) "
                            "ORDER BY c.lab_id,c.computer_id LIMIT 1 FOR UPDATE"));
                        pc->setInt(1,slot);
                        auto pr=unique_ptr<sql::ResultSet>(pc->executeQuery());
                        if(pr->next()) cid=pr->getInt(1);
                    }
                    if(cid==0) {
                        auto w=unique_ptr<sql::PreparedStatement>(db.get()->prepareStatement(
                            "UPDATE requests SET status='WAITING' WHERE request_id=?"));
                        w->setInt(1,r.id); w->executeUpdate();
                        db.get()->commit(); db.get()->setAutoCommit(true);
                        ++waiting; break;
                    }
                    auto ins=unique_ptr<sql::PreparedStatement>(db.get()->prepareStatement(
                        "INSERT INTO allocations(request_id,slot_id,computer_id,status) "
                        "VALUES(?,?,?,'ALLOCATED')"));
                    ins->setInt(1,r.id); ins->setInt(2,slot); ins->setInt(3,cid); ins->executeUpdate();
                    auto upd=unique_ptr<sql::PreparedStatement>(db.get()->prepareStatement(
                        "UPDATE requests SET status='ALLOCATED' WHERE request_id=?"));
                    upd->setInt(1,r.id); upd->executeUpdate();
                    db.get()->commit(); db.get()->setAutoCommit(true);
                    cout << "Request " << r.id << " allocated to computer " << cid << ".\n";
                    ++allocated; break;
                } catch(const sql::SQLException& e) {
                    try { db.get()->rollback(); db.get()->setAutoCommit(true); } catch(...) {}
                    const int code=e.getErrorCode();
                    if(code==1213 || code==1205) {
                        if(code==1213) ++deadlocks;
                        cout << "Database " << (code==1213 ? "deadlock detected" : "lock timeout")
                             << " for request " << r.id << "; transaction rolled back.\n";
                        if(attempt<2) continue;
                    }
                    cout << "Request " << r.id << " failed: " << e.what() << "\n";
                    ++failures; break;
                }
            }
        }
        cout << "Deadlock detection: " << deadlocks << " MySQL deadlock(s) detected and rolled back.\n";
        cout << "Scheduler completed: " << allocated << " allocated, " << waiting
             << " waiting, " << failures << " failed.\n";
    } catch(const sql::SQLException& e) {
        cout << "Scheduler database error: " << e.what() << "\n";
    }
}
